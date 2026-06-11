"""Live LLM smoke for choice_set design — SKIPPED by default.

Gated behind LIVE_API_TESTS=1 so CI / normal pytest runs cost nothing.
Validates that the configured model still responds correctly to the tool-use
prompt and returns a structurally valid choice set.

Run locally:
    LIVE_API_TESTS=1 SSL_CERT_FILE=<bundle> PYTHONPATH=src pytest tests/test_choice_set_live.py
"""

from __future__ import annotations

import os

import pytest

from arrival_agent.core.contract import ChoiceAxis
from arrival_agent.core.domain.choice_set import design_choice_set


pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_API_TESTS") != "1",
    reason="live API tests are opt-in (set LIVE_API_TESTS=1)",
)


CANDIDATES = [
    {"restaurant_id": "r1", "restaurant_name": "Lers Ros",
     "categories": ["Thai Restaurant"], "distance_m": 320},
    {"restaurant_id": "r2", "restaurant_name": "Pakwan",
     "categories": ["Indian Restaurant"], "distance_m": 480},
    {"restaurant_id": "r3", "restaurant_name": "Mixt",
     "categories": ["Salad Bar"], "distance_m": 520},
    {"restaurant_id": "r4", "restaurant_name": "Tony's Pizza",
     "categories": ["Pizza Place"], "distance_m": 610},
]

CONTEXT = {"time_of_day": "00:18", "city": "San Francisco", "fatigue": "high"}


def test_live_choice_set_structurally_valid():
    cs = design_choice_set(CANDIDATES, CONTEXT)
    # Axis must be valid enum
    assert isinstance(cs.axis, ChoiceAxis)
    assert cs.axis_reason
    # 2-3 options, each tied to a real candidate
    assert 2 <= len(cs.options) <= 3
    valid_ids = {c["restaurant_id"] for c in CANDIDATES}
    for o in cs.options:
        assert o.restaurant_id in valid_ids
        assert o.why_this_one
        assert o.est_total > 0
        assert o.items
    assert cs.why_these


def test_live_options_distinct_restaurants():
    """The LLM should not return three options pointing at the same place."""
    cs = design_choice_set(CANDIDATES, CONTEXT)
    ids = [o.restaurant_id for o in cs.options]
    assert len(set(ids)) == len(ids), f"duplicate restaurant_ids: {ids}"
