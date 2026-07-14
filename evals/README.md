# Evals

The agent's value is its *judgment*, which unit tests can't assert. These evals were
rebuilt after an **eval audit** (`/evals-skills:eval-audit`) that flagged real gaps —
an unvalidated 1-5 judge, 3-example datasets, no error analysis. What's here now follows
the fixes.

```bash
python -m evals.gen_synthetic --live   # generate the synthetic trace set (needs geo keys)
python -m evals.run                    # scorecard: properties + extraction + validation
python -m evals.validate               # just the TPR/TNR evaluator validation
EVAL_LIVE=1 python -m evals.run        # + the binary LLM axis-spread judge (needs a key)
```

## The pipeline (post-audit)

**1. Synthetic data → error analysis (`gen_synthetic.py`, `synthetic/`).**
No production traffic exists, so we generate diverse, failure-targeting traces (28
booking emails across formats chosen to stress each parser regex; 12 dinner rankings
across taste-profile × city, incl. international). `synthetic/FINDINGS.md` is the failure
taxonomy the traces revealed — including a real bug (**cuisine-misclassification**: greedy
"American" aliases tagged *Korean BBQ* as American), now fixed.

**2. Binary evaluators (`evaluators.py`).** One failure mode each, pass/fail (no 1-5
Likert — hard to calibrate/validate). Code-based where objectively checkable:

| Evaluator | Kind | Checks |
|---|---|---|
| `cuisine_match` | code | a badged "matches what you order" pick's cuisine is supported by the restaurant's real categories |
| `honest_copy` | code | "you order X most" only when X is the traveler's #1 cuisine |
| `extract:<field>` | code | booking-email field extracted correctly |
| `axis_spread` | **binary** LLM judge | do the choice-set options *meaningfully* differ along the stated axis? (replaces the old 1-5 quality score) |

**3. Labeled gold (`gold.py`).** Human (domain-expert) labels — good **and** failing
cases — so validation measures both TPR and TNR.

**4. Judge validation (`validate.py`).** TPR (of real failures, fraction caught) and TNR
(of good outputs, fraction not falsely flagged) against the gold labels — not raw
accuracy, which class imbalance makes misleading. Current:

```
cuisine_match   TPR 100%  TNR 100%   (n=11)
honest_copy     TPR 100%  TNR 100%   (n=6)
```

**5. Property invariants (`choice_set_eval.py`).** Code-based structural regression gate
over the golden choice sets (axis in enum, 2-3 distinct options, rationales present).

**6. CI gate (`tests/test_evals.py`).** Every run asserts: invariants hold, canonical
extraction is exact, and each binary evaluator still aligns with its labels (TPR/TNR = 1).
An evaluator that drifts goes red before it's trusted.

## Known gaps (honest, tracked)

- **Judge validation is under-powered:** only 3 golden choice sets exist to validate the
  `axis_spread` LLM judge against (target ~50 pass + 50 fail). Generating more needs the
  live `choice_set` LLM call — the next data-generation step.
- **Extraction is measured on the deterministic parser**; the actionable next eval is
  running the same 28 emails through the LLM path (`use_llm=True`) to quantify per-format
  recovery.
- **Secondary honesty finding** (surfaced by the improved eval): a "matches what you order"
  badge can land on a traveler's *lowest*-ranked cuisine when nothing better is open nearby
  (e.g. Ramen #6 for a burger-lover). `honest_copy` catches false "most" but not a weak
  "a lot" on a rarely-ordered cuisine — a candidate next evaluator + copy fix.
