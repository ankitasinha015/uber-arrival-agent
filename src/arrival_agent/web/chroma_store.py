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
            for k in range(n):
                dish = dishes[k % len(dishes)]
                eids.append(f"{tid}-{cuisine}-{k}")
                edocs.append(f"{dish} — {cuisine}")
                emeta.append({"traveler": tid, "cuisine": cuisine, "dish": dish})

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
