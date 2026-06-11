"""Tests for choice_set — the LLM-driven axis + options designer.

Hermetic: the Anthropic client is stubbed. Real LLM calls live in
test_choice_set_live.py (gated on LIVE_API_TESTS=1).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arrival_agent.core import metrics
from arrival_agent.core.contract import ChoiceAxis
from arrival_agent.core.domain.choice_set import design_choice_set


CANDIDATES = [
    {"restaurant_id": "r1", "restaurant_name": "Lers Ros",
     "categories": ["Thai Restaurant"], "distance_m": 320},
    {"restaurant_id": "r2", "restaurant_name": "Pakwan",
     "categories": ["Indian Restaurant"], "distance_m": 480},
    {"restaurant_id": "r3", "restaurant_name": "Mixt",
     "categories": ["Salad Bar"], "distance_m": 520},
]

CONTEXT = {"time_of_day": "00:18", "city": "San Francisco", "fatigue": "high"}


def _fake_client(tool_input: dict, in_tokens=420, out_tokens=180):
    """Build a stub client whose messages.create() returns a tool_use response."""
    tool_use_block = SimpleNamespace(type="tool_use", input=tool_input,
                                     name="design_choice_set", id="t1")
    resp = SimpleNamespace(
        content=[tool_use_block],
        usage=SimpleNamespace(input_tokens=in_tokens, output_tokens=out_tokens),
    )

    class _Messages:
        def create(self, **kwargs):
            return resp

    return SimpleNamespace(messages=_Messages())


def test_design_returns_valid_choice_set():
    client = _fake_client({
        "axis": "cuisine",
        "axis_reason": "User has variety in past picks",
        "options": [
            {"restaurant_id": "r1", "items": ["pad see ew", "spring rolls"],
             "est_total": 28, "why_this_one": "Your usual late-night pick"},
            {"restaurant_id": "r2", "items": ["chicken tikka", "naan"],
             "est_total": 32, "why_this_one": "Comfort food if you want warmth"},
            {"restaurant_id": "r3", "items": ["harvest bowl"],
             "est_total": 18, "why_this_one": "Light if you just want sleep"},
        ],
        "why_these_meta": "It's late and you flew 6h — here's variety vs comfort vs light.",
    })
    out = design_choice_set(CANDIDATES, CONTEXT, client=client)
    assert out.axis == ChoiceAxis.CUISINE
    assert len(out.options) == 3
    assert all(o.restaurant_id in {"r1", "r2", "r3"} for o in out.options)
    assert all(o.why_this_one for o in out.options)
    assert all(o.est_total > 0 for o in out.options)
    assert out.why_these


def test_design_accepts_two_options():
    client = _fake_client({
        "axis": "speed_vs_quality",
        "axis_reason": "ride is short, supply thin",
        "options": [
            {"restaurant_id": "r1", "items": ["pad thai"], "est_total": 22,
             "why_this_one": "Fast"},
            {"restaurant_id": "r3", "items": ["bowl"], "est_total": 18,
             "why_this_one": "Even faster, lighter"},
        ],
        "why_these_meta": "Both quick.",
    })
    out = design_choice_set(CANDIDATES, CONTEXT, client=client)
    assert len(out.options) == 2


def test_design_raises_when_llm_picks_unknown_restaurant():
    client = _fake_client({
        "axis": "cuisine", "axis_reason": "x",
        "options": [
            {"restaurant_id": "r1", "items": ["x"], "est_total": 10, "why_this_one": "ok"},
            {"restaurant_id": "GHOST", "items": ["y"], "est_total": 10, "why_this_one": "?"},
        ],
        "why_these_meta": "ok",
    })
    with pytest.raises(ValueError, match="unknown restaurant_id"):
        design_choice_set(CANDIDATES, CONTEXT, client=client)


def test_design_raises_when_fewer_than_two_options():
    client = _fake_client({
        "axis": "cuisine", "axis_reason": "x",
        "options": [{"restaurant_id": "r1", "items": ["x"],
                     "est_total": 10, "why_this_one": "ok"}],
        "why_these_meta": "ok",
    })
    with pytest.raises(ValueError, match="only 1"):
        design_choice_set(CANDIDATES, CONTEXT, client=client)


def test_design_raises_on_empty_candidates():
    with pytest.raises(ValueError, match="no candidates"):
        design_choice_set([], CONTEXT, client=_fake_client({}))


def test_design_records_llm_usage_in_metrics():
    client = _fake_client(
        {
            "axis": "cuisine", "axis_reason": "x",
            "options": [
                {"restaurant_id": "r1", "items": ["x"], "est_total": 10, "why_this_one": "a"},
                {"restaurant_id": "r2", "items": ["y"], "est_total": 12, "why_this_one": "b"},
            ],
            "why_these_meta": "ok",
        },
        in_tokens=500, out_tokens=200,
    )
    m = metrics.start_run()
    design_choice_set(CANDIDATES, CONTEXT, client=client)
    assert m.llm_calls == 1
    assert m.tokens_in == 500
    assert m.tokens_out == 200


def test_design_passes_past_picks_through_prompt_without_error():
    """Past picks shouldn't trip the prompt builder."""
    past = [
        {"restaurant_name": "Phi Sushi LAX", "cuisine_tags": ["Japanese"], "rating": 5},
        {"restaurant_name": "Lers Ros SF", "cuisine_tags": ["Thai"], "rating": 4},
    ]
    client = _fake_client({
        "axis": "familiarity_vs_novelty", "axis_reason": "user has favorites",
        "options": [
            {"restaurant_id": "r1", "items": ["pad thai"], "est_total": 24, "why_this_one": "your usual"},
            {"restaurant_id": "r2", "items": ["dal"], "est_total": 22, "why_this_one": "new comfort"},
        ],
        "why_these_meta": "your usual vs something new.",
    })
    out = design_choice_set(CANDIDATES, CONTEXT, past_picks=past, client=client)
    assert out.axis == ChoiceAxis.FAMILIARITY_VS_NOVELTY
