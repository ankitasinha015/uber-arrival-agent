"""The offline evals run in CI as a regression gate.

Property invariants must hold on every recorded golden choice set, and the
canonical extraction case must be exact. The variant-format extraction case is
allowed to miss (it documents the parser's known gap) — we only assert the
harness measures it, not that the deterministic parser is perfect.
"""

from __future__ import annotations

from evals.choice_set_eval import run_property_eval
from evals.extraction_eval import run_extraction_eval


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
