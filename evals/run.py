"""Eval runner — prints a scorecard.

  python -m evals.run                offline: properties + extraction
  EVAL_LIVE=1 python -m evals.run    + the LLM-as-judge quality score (needs a key)
"""

from __future__ import annotations

import os
import sys

from evals.choice_set_eval import run_judge_eval, run_property_eval
from evals.extraction_eval import run_extraction_eval


def main() -> int:
    live = os.environ.get("EVAL_LIVE") == "1"
    print("=" * 60)
    print("EVAL SCORECARD")
    print("=" * 60)

    # --- choice-set properties (regression baseline) ----------------------
    props = run_property_eval()
    passed = sum(1 for r in props if r["passed"])
    print(f"\nCHOICE-SET PROPERTIES  {passed}/{len(props)} golden sets pass all invariants")
    for r in props:
        if not r["passed"]:
            fails = [n for n, ok in r["checks"] if not ok]
            print(f"  FAIL {r['case']}: {', '.join(fails)}")
    if passed == len(props):
        inv = ", ".join(n for n, _ in props[0]["checks"]) if props else ""
        print(f"  invariants checked: {inv}")

    # --- extraction accuracy ---------------------------------------------
    ext = run_extraction_eval(use_llm=False)
    mean_acc = sum(r["accuracy"] for r in ext) / len(ext)
    print(f"\nEXTRACTION ACCURACY (deterministic parser)  mean {mean_acc:.0%}")
    for r in ext:
        miss = f"  misses: {', '.join(r['misses'])}" if r["misses"] else ""
        print(f"  {r['case']:16s} {r['accuracy']:.0%}{miss}")
    print("  (variant-format misses are the gap the LLM path is meant to close)")

    # --- LLM judge (quality) ---------------------------------------------
    if live:
        judged = run_judge_eval()
        scores = [j["score"] for j in judged if isinstance(j.get("score"), (int, float))]
        mean = sum(scores) / len(scores) if scores else 0
        print(f"\nCHOICE-SET QUALITY (LLM judge)  mean {mean:.1f}/5")
        for j in judged:
            print(f"  {j['case']}: {j.get('score')}/5 — {j.get('reason', '')}")
    else:
        print("\nCHOICE-SET QUALITY (LLM judge)  skipped — set EVAL_LIVE=1 (needs a key)")

    print("\n" + "=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
