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
    """Frequency claims must match the traveler's actual order rank:
      'you order X most' → only when X is the #1 cuisine;
      'you order X a lot' → only when X is in the top third of their taste.
    Neutral phrasings ('closest open option') are always fine."""
    w = (why or "").lower()
    pref = pref or _UBER_EATS_PREF
    rank = pref.index(claimed_cuisine) if claimed_cuisine in pref else 99
    if "most" in w:
        return ("honest_copy", rank == 0)
    if "a lot" in w:
        return ("honest_copy", rank < max(2, len(pref) // 2))
    return ("honest_copy", True)


# --- Extraction: field correctness (code) -------------------------------------

def check_extraction(got: dict, expected: dict, fields: list[str]):
    return [(f"extract:{f}", got.get(f) == expected.get(f)) for f in fields]


# --- Choice set: axis spread (binary LLM judge) -------------------------------

# Pin the judge model to a stable id. A floating alias can drift silently between
# provider updates; a dated snapshot keeps validated TPR/TNR meaningful.
JUDGE_MODEL = "claude-sonnet-4-5"


def _opts_str(cs: dict) -> str:
    return "; ".join(f"{o['restaurant_name']} ({o.get('why_this_one', '')})"
                     for o in cs.get("options", []))


def judge_axis_spread(cs: dict, examples=None, model: str = JUDGE_MODEL) -> dict:
    """BINARY replacement for the old 1-5 Likert quality judge. One question: do the
    options MEANINGFULLY differ along their stated axis? PASS/FAIL + reason. Optional
    few-shot `examples` = [(choice_set, pass_bool)] (from the TRAIN split only).
    Validated against human labels via validate_judge.py."""
    from arrival_agent.core.config import anthropic_key
    import anthropic

    shots = ""
    for ex_cs, ex_pass in (examples or []):
        shots += f"Axis '{ex_cs.get('axis')}': {_opts_str(ex_cs)}\n-> {{\"pass\": {str(bool(ex_pass)).lower()}}}\n\n"
    prompt = (
        "Decide if a dinner choice set's options MEANINGFULLY differ along their stated "
        "axis (a real, useful spread) rather than near-duplicates or varying on a "
        "DIFFERENT axis than the one stated.\n"
        "An axis is spread when the options sit at DIFFERENT points on it:\n"
        "- cuisine: different cuisines;\n"
        "- speed_vs_quality: quick vs balanced vs best/slower;\n"
        "- volume: a light bite vs a meal vs a feast;\n"
        "- familiarity_vs_novelty: a usual favorite vs a new/novel pick vs a lighter/safer option.\n"
        "PASS as long as the options occupy different points on the stated axis. FAIL only "
        "near-duplicates, or options that vary on a different axis than the one stated.\n\n"
        + (f"Examples:\n{shots}" if shots else "")
        + f"Now judge this one.\nAxis '{cs.get('axis')}': {_opts_str(cs)}\n"
        'Reply ONLY JSON: {"pass": true|false, "reason": "<one short line>"}.'
    )
    client = anthropic.Anthropic(api_key=anthropic_key())
    resp = client.messages.create(model=model, max_tokens=120,
                                  messages=[{"role": "user", "content": prompt}])
    text = "".join(getattr(b, "text", "") for b in resp.content)
    m = re.search(r"\{[^{}]*\}", text, re.S)   # first flat JSON object (robust to extra text)
    try:
        return json.loads(m.group(0)) if m else {"pass": None, "reason": text[:100]}
    except Exception:
        return {"pass": None, "reason": text[:100]}
