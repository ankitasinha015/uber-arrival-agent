# Retrieval eval — ChromaDB taste store (`/evals-skills:evaluate-rag`)

## Is this even RAG? (error analysis first)

No — not classic retrieve→LLM-generate. ChromaDB holds the traveler's Uber Eats order
history as embedded vectors; the product ranks dinner by cuisine **frequency** (code),
not vector retrieval. An earlier vector-ranking attempt (`rank_by_order_pattern`) was
**rejected** because it ranked worse (burger spots first for a Mexican-lover). So the
useful RAG eval is to quantify the vector store's *retrieval* quality and settle whether
retrieval was the bottleneck. `python -m evals.retrieval_eval`.

## Task & metrics

Query = a restaurant (name + Foursquare category) of known cuisine C. Relevant = the
traveler's past orders of cuisine C. Retrieve top-k orders by vector similarity. Single-
fact-lookup shape → **MRR** primary (per the skill), plus Precision@1 and Hit@3.

## Results (traveler=marcus, k=5)

```
Precision@1 100%   Hit@3 100%   MRR 1.00
```

Every clean query retrieves a same-cuisine order at rank 1 ("Ippudo — Ramen Restaurant"
→ a Ramen order). **Retrieval is NOT the bottleneck.**

Per the skill's diagnosis table (high context relevance, bad downstream) this pins the
earlier vector-ranking failure on **scoring, not retrieval**: raw cross-restaurant
similarity isn't calibrated across cuisines and ignores order *frequency*, so it's the
wrong signal for ranking restaurants by preference. Cuisine-frequency (what we ship) is
correct; retrieval is sound.

## Adversarial probe (the categories that caused the misclassification bug)

| Ambiguous query | nearest order | similarity |
|---|---|---|
| Moonhan Korean BBQ — Korean BBQ Restaurant | Thai | **0.37** |
| Tommy's Bar and Grill — Bar, American Restaurant | American | 0.51 |
| Kinder's Meats BBQ — BBQ Joint | American | 0.53 |

The store **hedges** on ambiguous cuisines with low similarity — Korean BBQ lands at
0.37, not a confident American/Burger match. So the *retrieval* layer would **not** have
made the confident "Korean BBQ = American" error the regex aliases did.

## Evidence-backed recommendation

A **similarity-thresholded vector classifier** would classify restaurant cuisine more
robustly than `_CUISINE_ALIASES`: retrieve the nearest reference order/exemplar, accept
the cuisine only above a confidence threshold (~0.6), and gate the "matches what you
order" badge on that confidence. It would have caught Korean BBQ (0.37 < threshold →
"no confident match") without a hand-maintained alias list. Not shipped (the alias fix +
`cuisine_match` evaluator already close the bug); logged as the next retrieval-driven
improvement.

## Honest limitations

- Tiny query set (6 clean + 3 adversarial), one traveler, and Marcus's history is skewed
  (Burger×9 … Ramen×1) so top-5 is burger-heavy. A larger, multi-traveler query set with
  more adversarial cases (via the skill's adversarial-generation process) would tighten
  the numbers.
- No generation half to evaluate (no RAG generation step exists), so faithfulness /
  answer-relevance metrics don't apply here.
