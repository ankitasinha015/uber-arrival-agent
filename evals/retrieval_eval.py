"""Retrieval eval for the ChromaDB taste store (evals-skills:evaluate-rag).

This app is NOT classic RAG (no retrieve->LLM-generate). Chroma holds the traveler's
Uber Eats order history as embedded vectors; the product ranks dinner by
cuisine-FREQUENCY (code), not vector retrieval — because an earlier vector-ranking
attempt ranked worse. This eval QUANTIFIES that: treat "given a restaurant, retrieve
this traveler's most-similar past orders" as the retrieval task and measure whether the
top hits share the restaurant's cuisine.

Task per query: a restaurant (name + Foursquare-style category) of a known cuisine C.
Relevant = the traveler's past orders whose cuisine is C. Retrieve top-k orders from
Chroma by vector similarity; score.

Metrics (single-fact-lookup shape → MRR is primary, per the skill):
  Precision@1   top-1 retrieved order is cuisine C
  Hit@3         a cuisine-C order appears in the top 3
  MRR           1 / rank of the first cuisine-C order (0 if none in top-k)

Run:  CONCIERGE_CHROMA=1 HF_HUB_OFFLINE=1 python -m evals.retrieval_eval
"""

from __future__ import annotations

# realistic restaurant queries (name — category), one per canonical cuisine
QUERIES = [
    ("Ippudo — Ramen Restaurant", "Ramen"),
    ("Taqueria Cancún — Mexican Restaurant", "Mexican"),
    ("Osha Thai — Thai Restaurant", "Thai"),
    ("Shake Shack — Burger Joint", "Burger"),
    ("The Smith — American Restaurant", "American"),
    ("Joe's Pizza — Pizzeria", "Pizza"),
]
# Adversarial: ambiguous category text that lexically overlaps a taste bucket but is a
# DIFFERENT cuisine (these caused the alias-based misclassification bug). We report what
# the store retrieves + its distance, to see if it mis-matches confidently or hedges.
ADVERSARIAL = [
    "Moonhan Korean BBQ — Korean BBQ Restaurant",   # Korean, tempted 'BBQ'->American/Burger
    "Tommy's Bar and Grill — Bar, American Restaurant",
    "Kinder's Meats BBQ — BBQ Joint",
]
K = 5


def evaluate(traveler: str = "marcus") -> dict:
    from arrival_agent.web import chroma_store as cs
    eats = cs.client().get_or_create_collection("eats_orders")
    qvecs = cs._embed([q for q, _ in QUERIES])

    rows = []
    for (qtext, cuisine), qv in zip(QUERIES, qvecs):
        res = eats.query(query_embeddings=[qv], where={"traveler": traveler},
                         n_results=K, include=["metadatas"])
        got = [m.get("cuisine") for m in (res.get("metadatas") or [[]])[0]]
        first = next((i + 1 for i, c in enumerate(got) if c == cuisine), None)
        rows.append({
            "query": qtext, "cuisine": cuisine, "retrieved": got,
            "p@1": got[:1] == [cuisine],
            "hit@3": cuisine in got[:3],
            "rr": (1.0 / first) if first else 0.0,
        })
    n = len(rows)
    return {
        "traveler": traveler, "k": K, "rows": rows,
        "P@1": sum(r["p@1"] for r in rows) / n,
        "Hit@3": sum(r["hit@3"] for r in rows) / n,
        "MRR": sum(r["rr"] for r in rows) / n,
    }


def adversarial(traveler: str = "marcus"):
    from arrival_agent.web import chroma_store as cs
    eats = cs.client().get_or_create_collection("eats_orders")
    qvecs = cs._embed(ADVERSARIAL)
    out = []
    for q, qv in zip(ADVERSARIAL, qvecs):
        res = eats.query(query_embeddings=[qv], where={"traveler": traveler},
                         n_results=1, include=["metadatas", "distances"])
        m = (res.get("metadatas") or [[{}]])[0][0]
        d = (res.get("distances") or [[None]])[0][0]
        out.append((q, m.get("cuisine"), 1.0 - float(d) if d is not None else None))
    return out


def main() -> int:
    r = evaluate()
    print("=" * 64)
    print(f"CHROMA TASTE-STORE RETRIEVAL  (traveler={r['traveler']}, k={r['k']})")
    print("=" * 64)
    for row in r["rows"]:
        tag = "✓" if row["p@1"] else ("~" if row["hit@3"] else "✗")
        print(f"  {tag} {row['cuisine']:9} query → top{r['k']}: {row['retrieved']}")
    print("-" * 64)
    print(f"  Precision@1 {r['P@1']:.0%}   Hit@3 {r['Hit@3']:.0%}   MRR {r['MRR']:.2f}")
    print("\nADVERSARIAL (ambiguous categories) — nearest order + similarity:")
    for q, cuisine, sim in adversarial(r["traveler"]):
        s = f"{sim:.2f}" if sim is not None else "—"
        print(f"  {q[:44]:44} → {cuisine:8} (sim {s})")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
