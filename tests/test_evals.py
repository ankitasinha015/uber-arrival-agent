"""The offline evals run in CI as a regression gate.

After the eval-audit fixes, CI asserts three things stay true:
  1. property invariants hold on every golden choice set (regression baseline);
  2. the canonical extraction case is exact (the variant is allowed to miss — it
     documents the parser's known gap; we only assert the harness measures it);
  3. every binary evaluator still ALIGNS with its human labels — perfect TPR (catches
     all labelled failures) and perfect TNR (no false alarms). If an evaluator drifts,
     this goes red before the evaluator is trusted in a scorecard.
"""

from __future__ import annotations

from evals.choice_set_eval import run_property_eval
from evals.extraction_eval import run_extraction_eval
from evals.validate import validate_cuisine_match, validate_honest_copy


def test_all_golden_choice_sets_pass_invariants():
    results = run_property_eval()
    assert results, "no golden choice sets found to eval"
    bad = [r["case"] for r in results if not r["passed"]]
    assert not bad, f"choice-set invariants failed for: {bad}"


def test_canonical_extraction_is_exact():
    rows = {r["case"]: r for r in run_extraction_eval(use_llm=False)}
    assert rows["canonical"]["accuracy"] == 1.0


def test_extraction_harness_measures_the_variant_gap():
    rows = {r["case"]: r for r in run_extraction_eval(use_llm=False)}
    # the variant uses "Accommodation:" not "hotel:" — the eval should catch the miss
    assert "hotel" in rows["variant-format"]["misses"]
    assert rows["variant-format"]["accuracy"] < 1.0


def test_cuisine_match_evaluator_aligns_with_labels():
    r = validate_cuisine_match()
    assert r["TPR"] == 1.0, f"cuisine_match missed a labelled failure: {r}"
    assert r["TNR"] == 1.0, f"cuisine_match false-flagged a good output: {r}"


def test_honest_copy_evaluator_aligns_with_labels():
    r = validate_honest_copy()
    assert r["TPR"] == 1.0, f"honest_copy missed a labelled failure: {r}"
    assert r["TNR"] == 1.0, f"honest_copy false-flagged a good output: {r}"
