"""Eval: the choice-set design — property invariants (the code-based regression gate).

Hard invariants EVERY choice set must satisfy, run over the recorded golden outputs:
if a prompt change starts producing 4 options or an invalid axis, this goes red.

The subjective "do the options vary along the axis" judgment is NOT here — after the
eval-audit it's a BINARY judge in `evals.evaluators.judge_axis_spread` (the old 1-5
Likert score was removed: hard to calibrate, hard to validate), validated in
`evals.validate`.

Run:  python -m evals.run          (properties, offline)
"""

from __future__ import annotations

import json
from pathlib import Path

from arrival_agent.core.contract import ChoiceAxis

_GOLDEN = Path(__file__).resolve().parents[1] / "scenarios" / "cache" / "choice_set"


def _load_golden() -> list[tuple[str, dict]]:
    return [(p.name, json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(_GOLDEN.glob("*.json"))]


def check_properties(cs: dict) -> list[tuple[str, bool]]:
    """The invariants. Each returns (name, passed)."""
    axes = {a.value for a in ChoiceAxis}
    opts = cs.get("options", [])
    ids = [o.get("restaurant_id") for o in opts]
    return [
        ("axis in enum", cs.get("axis") in axes),
        ("2-3 options", 2 <= len(opts) <= 3),
        ("distinct restaurants", len(ids) == len(set(ids)) and all(ids)),
        ("positive totals", all((o.get("est_total") or 0) > 0 for o in opts)),
        ("per-option rationale", all((o.get("why_this_one") or "").strip() for o in opts)),
        ("set rationale", bool((cs.get("why_these") or "").strip())),
        ("axis reasoned", bool((cs.get("axis_reason") or "").strip())),
    ]


def run_property_eval() -> list[dict]:
    out = []
    for name, cs in _load_golden():
        checks = check_properties(cs)
        out.append({"case": name, "checks": checks, "passed": all(ok for _, ok in checks)})
    return out
