"""Binary, single-failure-mode evaluators — the eval-audit "Evaluator Design" fix.

Each evaluator checks ONE failure mode and returns a binary pass/fail (no 1-5 Likert
scales — those are hard to calibrate and validate). Code-based wherever the failure is
objectively checkable; an LLM judge only for the genuinely subjective one. Every
evaluator is validated against human labels in `gold.py` (TPR/TNR via `validate.py`).

Failure modes (from error analysis on the synthetic traces, see synthetic/FINDINGS.md):
  cuisine_match   a badged "matches what you order" pick's cuisine must be supported
                  by the restaurant's real categories (caught Korean BBQ tagged American)
  honest_copy     "you order X most" only when X is the traveler's #1 cuisine
  extract:<field> booking-email field extracted correctly
  axis_spread     (LLM) do the choice-set options meaningfully differ along the axis
"""

from __future__ import annotations

import json
import re

from arrival_agent.web.concierge import _CUISINE_ALIASES, _UBER_EATS_PREF


# --- Ranking: cuisine misclassification (code) --------------------------------

def check_cuisine_match(claimed_cuisine: str, categories: list[str], badged: bool):
    """If an option is presented as one of the traveler's TASTE cuisines (badged
    'matches what you order' / 'a cuisine you order'), that cuisine's aliases must
    actually appear in the restaurant's categories. FAIL catches e.g. a Korean BBQ
    place tagged 'American'. An honest generic label (un-badged) always passes."""
    if not badged or claimed_cuisine not in _CUISINE_ALIASES:
        return ("cuisine_match", True)
    blob = " ".join(categories).lower()
    return ("cuisine_match", any(a in blob for a in _CUISINE_ALIASES[claimed_cuisine]))


# --- Ranking: copy honesty (code) ---------------------------------------------

def check_honest_copy(why: str, claimed_cuisine: str, pref: list[str]):
    """'you order X most' may only appear when X is the traveler's #1 cuisine.
    'a lot' / other phrasings are always fine."""
    if "most" not in (why or "").lower():
        return ("honest_copy", True)
    top = (pref or _UBER_EATS_PREF)[0]
    return ("honest_copy", claimed_cuisine == top)


# --- Extraction: field correctness (code) -------------------------------------

def check_extraction(got: dict, expected: dict, fields: list[str]):
    return [(f"extract:{f}", got.get(f) == expected.get(f)) for f in fields]


# --- Choice set: axis spread (binary LLM judge) -------------------------------

def judge_axis_spread(cs: dict) -> dict:
    """BINARY replacement for the old 1-5 Likert quality judge. One question:
    do the options MEANINGFULLY differ along their stated axis? PASS/FAIL, with a
    reason. Live LLM call; validated against human labels in gold.py."""
    from arrival_agent.core.config import anthropic_key
    import anthropic

    opts = "; ".join(
        f"{o['restaurant_name']} ({o.get('why_this_one', '')})" for o in cs.get("options", [])
    )
    prompt = (
        f"A late-night arrival agent built a dinner choice set on the axis "
        f"'{cs.get('axis')}'. Options: {opts}.\n\n"
        "Question: do these options MEANINGFULLY differ along that stated axis (a real, "
        "useful spread), rather than being near-duplicates or varying on a different "
        "axis than the one stated? Reply ONLY JSON: "
        '{"pass": true|false, "reason": "<one short line>"}.'
    )
    client = anthropic.Anthropic(api_key=anthropic_key())
    resp = client.messages.create(
        model="claude-sonnet-4-5", max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(b, "text", "") for b in resp.content)
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {"pass": None, "reason": text[:100]}
