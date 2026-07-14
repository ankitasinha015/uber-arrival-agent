"""Validate the evaluators against human labels — the eval-audit "Judge Validation" fix.

Measures TPR (of real failures, the fraction the evaluator catches) and TNR (of good
outputs, the fraction it does NOT falsely flag) against the labeled gold set. TPR/TNR,
not raw accuracy — with class imbalance, accuracy hides a judge that rubber-stamps
everything. The FAIL class is the "positive".

Code evaluators (cuisine_match, honest_copy) validate offline. The LLM axis-spread
judge validates only with EVAL_LIVE=1 (needs a key).
"""

from __future__ import annotations

import os


def _rates(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs = [(verdict_pass, gold_pass)]; positive class = FAIL."""
    tp = fn = tn = fp = 0
    for verdict_pass, gold_pass in pairs:
        if not gold_pass:                      # a real failure
            tp += (not verdict_pass)           # caught
            fn += verdict_pass                 # missed
        else:                                  # a good output
            tn += verdict_pass                 # correctly passed
            fp += (not verdict_pass)           # false alarm
    return {
        "n": len(pairs), "TP": tp, "FN": fn, "TN": tn, "FP": fp,
        "TPR": (tp / (tp + fn)) if (tp + fn) else None,
        "TNR": (tn / (tn + fp)) if (tn + fp) else None,
    }


def validate_cuisine_match() -> dict:
    from evals.evaluators import check_cuisine_match
    from evals.gold import CUISINE_MATCH_GOLD
    pairs = [(check_cuisine_match(c, cats, b)[1], gold)
             for c, cats, b, gold, _ in CUISINE_MATCH_GOLD]
    return _rates(pairs)


def validate_honest_copy() -> dict:
    from evals.evaluators import check_honest_copy
    from evals.gold import HONEST_COPY_GOLD
    pairs = [(check_honest_copy(why, c, pref)[1], gold)
             for why, c, pref, gold, _ in HONEST_COPY_GOLD]
    return _rates(pairs)


def validate_axis_spread() -> dict:
    from evals.evaluators import judge_axis_spread
    from evals.gold import choice_set_gold
    pairs = [(bool(judge_axis_spread(cs).get("pass")), gold) for cs, gold in choice_set_gold()]
    return _rates(pairs)


def _fmt(r: dict) -> str:
    tpr = f"{r['TPR']:.0%}" if r["TPR"] is not None else "—"
    tnr = f"{r['TNR']:.0%}" if r["TNR"] is not None else "—"
    return f"TPR {tpr}  TNR {tnr}   (n={r['n']}  TP={r['TP']} FN={r['FN']} TN={r['TN']} FP={r['FP']})"


def main() -> int:
    print("=" * 60)
    print("EVALUATOR VALIDATION  (vs human labels — TPR/TNR)")
    print("=" * 60)
    print(f"cuisine_match   {_fmt(validate_cuisine_match())}")
    print(f"honest_copy     {_fmt(validate_honest_copy())}")
    if os.environ.get("EVAL_LIVE") == "1":
        print(f"axis_spread     {_fmt(validate_axis_spread())}   (LLM judge)")
    else:
        print("axis_spread     skipped — EVAL_LIVE=1 to validate the LLM judge (needs a key)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
