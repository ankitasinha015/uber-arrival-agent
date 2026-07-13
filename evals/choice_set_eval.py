"""Eval: the choice-set design — the agent's core LLM judgment.

Two methods, the two that matter for an LLM output:

  properties  Hard invariants EVERY choice set must satisfy, run over the recorded
              golden outputs. This is a regression baseline: if a prompt change
              starts producing 4 options or an invalid axis, this goes red.

  judge       An LLM scores quality 1-5: do the options genuinely vary along their
              stated axis in a way useful to a tired late-night traveler? Subjective
              quality can't be asserted, so we measure it. Gated on EVAL_LIVE=1.

Run:  python -m evals.run          (properties, offline)
      EVAL_LIVE=1 python -m evals.run   (+ the LLM judge, needs a key)
"""

from __future__ import annotations

import json
import re
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


def judge_quality(cs: dict) -> dict:
    """LLM-as-judge: score the set's quality 1-5. Live call."""
    from arrival_agent.core.config import anthropic_key
    import anthropic

    opts = "; ".join(
        f"{o['restaurant_name']} ({o.get('why_this_one', '')})" for o in cs.get("options", [])
    )
    prompt = (
        f"A late-night airport-arrival agent designed a dinner choice set on the axis "
        f"'{cs.get('axis')}'. The options: {opts}.\n\n"
        "Rate 1-5 how well these options genuinely vary along that axis in a way useful "
        "to a tired traveler who just landed after a delayed flight. 5 = a sharp, "
        "meaningful spread; 1 = redundant or off-axis. Reply ONLY with JSON: "
        '{"score": <int 1-5>, "reason": "<one short line>"}.'
    )
    client = anthropic.Anthropic(api_key=anthropic_key())
    resp = client.messages.create(
        model="claude-sonnet-4-5", max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(b, "text", "") for b in resp.content)
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {"score": None, "reason": text[:100]}


def run_judge_eval() -> list[dict]:
    return [{"case": name, **judge_quality(cs)} for name, cs in _load_golden()]
