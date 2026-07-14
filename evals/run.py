"""Eval runner — prints a scorecard.

  python -m evals.run                offline: properties + extraction + evaluator validation
  EVAL_LIVE=1 python -m evals.run    + the LLM axis-spread judge (binary, needs a key)

After the eval-audit fixes this covers: code-based regression invariants, extraction
accuracy, a BINARY (not 1-5) LLM judge, and TPR/TNR VALIDATION of every evaluator
against human labels — so the numbers here are trustworthy, not vanity.
"""

from __future__ import annotations

import os
import sys

from evals.choice_set_eval import run_property_eval
from evals.extraction_eval import run_extraction_eval
from evals.validate import (_fmt, validate_axis_spread, validate_cuisine_match,
                            validate_honest_copy)


def main() -> int:
    live = os.environ.get("EVAL_LIVE") == "1"
    print("=" * 60)
    print("EVAL SCORECARD")
    print("=" * 60)

    # --- choice-set properties (code, regression baseline) ----------------
    props = run_property_eval()
    passed = sum(1 for r in props if r["passed"])
    print(f"\nCHOICE-SET PROPERTIES  {passed}/{len(props)} golden sets pass all invariants")
    for r in props:
        if not r["passed"]:
            print(f"  FAIL {r['case']}: {', '.join(n for n, ok in r['checks'] if not ok)}")

    # --- extraction accuracy (code) --------------------------------------
    ext = run_extraction_eval(use_llm=False)
    mean_acc = sum(r["accuracy"] for r in ext) / len(ext)
    print(f"\nEXTRACTION ACCURACY (deterministic parser)  mean {mean_acc:.0%}")
    for r in ext:
        miss = f"  misses: {', '.join(r['misses'])}" if r["misses"] else ""
        print(f"  {r['case']:16s} {r['accuracy']:.0%}{miss}")

    # --- evaluator validation (TPR/TNR vs human labels) ------------------
    print("\nEVALUATOR VALIDATION  (binary evaluators vs human labels)")
    print(f"  cuisine_match   {_fmt(validate_cuisine_match())}")
    print(f"  honest_copy     {_fmt(validate_honest_copy())}")
    if live:
        print(f"  axis_spread     {_fmt(validate_axis_spread())}   (LLM judge)")
    else:
        print("  axis_spread     skipped — EVAL_LIVE=1 to validate the LLM judge")

    print("\n" + "=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
