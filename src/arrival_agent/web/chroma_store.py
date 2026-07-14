"""ChromaDB-backed synthetic data store for the concierge.

Real trip data isn't available, so we seed **synthetic** data into ChromaDB and the
app reads from it at runtime — the same shape a real backend would have. Chroma runs
in Docker (native crashes on this machine); the app talks to it over HTTP, so the
Rust core runs in the container and the Python side just makes network calls.

Two collections:
  travelers    — one record per traveler; metadata carries the full trip profile
                 (persona JSON). The login roster + every trip fact loads from here.
  eats_orders  — synthetic Uber Eats order history, many rows per traveler, each an
                 embedded past order (dish + cuisine). The dinner **taste ranking**
                 is derived from THIS (aggregate the cuisines a traveler orders),
                 not a hardcoded list — the first-party-data "moat", now data-driven.

Embeddings are computed locally from the cached MiniLM model (HF_HUB_OFFLINE) and
passed to Chroma; the container stores/searches them, no model server-side.

Everything is gated behind CONCIERGE_CHROMA=1 (the web server sets it) so tests and
plain imports never require a running container — they fall back to the in-code seed.
"""

from __future__ import annotations

import json
import os
from collections import Counter

_HOST = os.environ.get("CHROMA_HOST", "localhost")
_PORT = int(os.environ.get("CHROMA_PORT", "8001"))

_client = None
_model = None

# Synthetic Uber Eats dishes per cuisine — the order history is generated from these.
_DISHES = {
    "Ramen": ["Tonkotsu Ramen", "Spicy Miso Ramen", "Shoyu Ramen"],
    "Mexican": ["Carnitas Burrito", "Al Pastor Tacos", "Chicken Quesadilla"],
    "Thai": ["Pad Thai", "Green Curry", "Pad See Ew"],
    "Burger": ["Double Cheeseburger", "Bacon Burger", "Classic Smashburger"],
    "American": ["Half Roast Chicken", "BBQ Ribs", "Buffalo Wings"],
    "Pizza": ["Margherita Pizza", "Pepperoni Pizza", "Marinara Slice"],
}
# Restaurants the (synthetic) orders came from — real chain/spot names per cuisine.
_EATS_SPOTS = {
    "Ramen": ["Ippudo", "Totto Ramen", "Jinya Ramen Bar"],
    "Mexican": ["Chipotle", "Taqueria Cancún", "El Farolito"],
    "Thai": ["Thai Basil", "Lers Ros", "Farmhouse Kitchen"],
    "Burger": ["Shake Shack", "Five Guys", "Super Duper Burgers"],
    "American": ["The Cheesecake Factory", "Cracker Barrel", "The Smith"],
    "Pizza": ["Joe's Pizza", "Blaze Pizza", "Prince Street Pizza"],
}
_BASE_PRICE = {"Ramen": 18, "Mexican": 15, "Thai": 20, "Burger": 16, "American": 24, "Pizza": 19}
# past-order counts by taste rank — the top cuisine is ordered the most.
_ORDER_WEIGHTS = [9, 6, 4, 3, 2, 1]


def client():
    global _client
    if _client is None:
        import chromadb
        _client = chromadb.HttpClient(host=_HOST, port=_PORT)
    return _client


def available() -> bool:
    try:
        client().heartbeat()
        return True
    except Exception:
        return False


def _embed(texts: list[str]) -> list[list[float]]:
    global _model
    if _model is None:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return [v.tolist() for v in _model.encode(texts, normalize_embeddings=True)]


def seed(travelers: dict) -> tuple[int, int]:
    """Wipe + reseed both collections from the synthetic traveler dict. Returns
    (traveler_count, order_count)."""
    c = client()
    for name in ("travelers", "eats_orders"):
        try:
            c.delete_collection(name)
        except Exception:
            pass
    trav = c.get_or_create_collection("travelers")
    eats = c.get_or_create_collection("eats_orders", metadata={"hnsw:space": "cosine"})

    tids, tdocs, tmeta = [], [], []
    eids, edocs, emeta = [], [], []
    for tid, p in travelers.items():
        taste = p.get("taste", [])
        tids.append(tid)
        tdocs.append(f"{p.get('name', tid)} — orders {', '.join(taste[:3])}")
        tmeta.append({"persona": json.dumps(p), "name": p.get("name", tid), "city": p.get("city", "")})
        for rank, cuisine in enumerate(taste):
            n = _ORDER_WEIGHTS[rank] if rank < len(_ORDER_WEIGHTS) else 1
            dishes = _DISHES.get(cuisine, [f"{cuisine} dish"])
            spots = _EATS_SPOTS.get(cuisine, [f"{cuisine} Place"])
            base = _BASE_PRICE.get(cuisine, 18)
            for k in range(n):
                dish = dishes[k % len(dishes)]
                spot = spots[k % len(spots)]
                price = round(base + (k % 3) * 2.5 + rank * 0.5, 2)
                days_ago = rank * 6 + k * 2 + 1          # spread over the last ~3 months
                eids.append(f"{tid}-{cuisine}-{k}")
                edocs.append(f"{dish} from {spot} — {cuisine}")
                emeta.append({"traveler": tid, "cuisine": cuisine, "dish": dish,
                              "restaurant": spot, "price": price, "days_ago": days_ago})

    trav.add(ids=tids, documents=tdocs, embeddings=_embed(tdocs), metadatas=tmeta)
    eats.add(ids=eids, documents=edocs, embeddings=_embed(edocs), metadatas=emeta)
    return len(tids), len(eids)


def load_travelers() -> dict:
    """Read every traveler's trip profile back out of Chroma into the persona-dict
    shape the app already uses. {} if the collection is empty/unreachable."""
    got = client().get_or_create_collection("travelers").get(include=["metadatas"])
    out = {}
    for tid, meta in zip(got.get("ids", []) or [], got.get("metadatas", []) or []):
        try:
            out[tid] = json.loads(meta["persona"])
        except Exception:
            pass
    return out


def taste_for(tid: str) -> list[str]:
    """Ranked cuisines for a traveler, DERIVED from their Uber Eats order history in
    Chroma (most-ordered cuisine first). [] if unavailable."""
    got = client().get_or_create_collection("eats_orders").get(
        where={"traveler": tid}, include=["metadatas"]
    )
    counts = Counter(m["cuisine"] for m in (got.get("metadatas", []) or []))
    return [cz for cz, _ in counts.most_common()]


# Cuisine exemplars — a few reference phrases per taste cuisine. A restaurant is
# classified by cosine similarity to these, with a CONFIDENCE THRESHOLD: below it we
# return None (honest "unknown") instead of forcing a weak match. This replaces the
# greedy regex aliases (which mis-bucketed Korean BBQ as American); the RAG eval showed
# the vector store hedges on ambiguous cuisines (Korean BBQ → ~0.37), so a threshold
# rejects them cleanly.
_CUISINE_EXEMPLARS = {
    "Ramen": ["ramen restaurant", "japanese ramen noodle house", "tonkotsu ramen shop"],
    "Mexican": ["mexican restaurant", "taqueria tacos burritos", "tex-mex cantina"],
    "Thai": ["thai restaurant", "pad thai green curry noodles"],
    "Burger": ["burger joint", "cheeseburger fast food", "smashburger shack"],
    "American": ["american restaurant", "diner comfort food", "new american bistro"],
    "Pizza": ["pizzeria", "italian pizza restaurant", "neapolitan pizza"],
}
_exemplar_vecs = None
# Calibrated on clean vs adversarial restaurants: confident correct matches score
# 0.72–0.81 (Shake Shack→Burger, Ippudo→Ramen, Los Tacos→Mexican); every ambiguous
# case falls ≤0.56 (Korean BBQ→0.55, sushi→0.56, German→0.53, French→0.47). 0.60
# sits in the clean gap — confident matches pass, everything ambiguous → None (honest).
CLASSIFY_THRESHOLD = 0.60


def _cuisine_exemplars():
    global _exemplar_vecs
    if _exemplar_vecs is None:
        import numpy as np
        _exemplar_vecs = {cz: np.mean(_embed(ph), axis=0) for cz, ph in _CUISINE_EXEMPLARS.items()}
    return _exemplar_vecs


def classify_cuisine(name: str, categories: list[str], cuisines: list[str],
                     threshold: float = CLASSIFY_THRESHOLD):
    """Best-matching taste cuisine for a restaurant, by vector similarity to exemplars.
    Returns (cuisine, score) above the threshold, else (None, score) — an honest
    'no confident match' rather than a forced weak one. `cuisines` scopes the buckets."""
    import numpy as np
    v = np.array(_embed([f"{name} — {', '.join(categories)}"])[0])
    ex = _cuisine_exemplars()
    best, best_s = None, -1.0
    for cz in cuisines:
        e = ex.get(cz)
        if e is None:
            continue
        s = float(np.dot(v, e) / ((np.linalg.norm(v) * np.linalg.norm(e)) or 1))
        if s > best_s:
            best, best_s = cz, s
    return (best, round(best_s, 3)) if best_s >= threshold else (None, round(best_s, 3))


def top_dish(tid: str, cuisine: str) -> str | None:
    """The traveler's most-ordered DISH in a cuisine, from their Chroma order
    history — used to explain a suggestion ('you order Double Cheeseburgers')."""
    got = client().get_or_create_collection("eats_orders").get(
        where={"$and": [{"traveler": tid}, {"cuisine": cuisine}]}, include=["metadatas"]
    )
    dishes = Counter(m.get("dish") for m in (got.get("metadatas", []) or []) if m.get("dish"))
    top = dishes.most_common(1)
    return top[0][0] if top else None


def inventory() -> tuple[dict, list[dict]]:
    """Everything currently in the store: (travelers dict, list of eats orders).
    Used to show exactly what synthetic data exists."""
    c = client()
    tg = c.get_or_create_collection("travelers").get(include=["metadatas"])
    travelers = {}
    for tid, meta in zip(tg.get("ids", []) or [], tg.get("metadatas", []) or []):
        try:
            travelers[tid] = json.loads(meta["persona"])
        except Exception:
            pass
    eg = c.get_or_create_collection("eats_orders").get(include=["metadatas"])
    orders = [{"id": oid, **meta}
              for oid, meta in zip(eg.get("ids", []) or [], eg.get("metadatas", []) or [])]
    return travelers, orders
