"""Hermetic end-to-end tests for the LangGraph adapter.

All I/O is stubbed (Mapbox ETA, Foursquare search, the LLM choice-set call,
the order mock is already a mock). What's REAL here is the LangGraph machinery:
the StateGraph, the checkpointer carrying state across per-event invocations,
and the native interrupt at the choice moment.

The headline test replays the full delayed-flight scenario:
    trip_booked -> WAIT (loose estimate)
    flight delayed -> WAIT
    flight on_ground -> WAIT
    ride_started -> SURFACE (estimate tight; 3 options via stubbed LLM)
    order_rejected -> SURFACE again (recovery: dead option swapped out)
    ride_ended / check_in -> SURFACE re-emitted (still waiting for pick)
    user_pick -> PLACED
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arrival_agent.core.contract import Action, ChoiceAxis, ChoiceOption
from arrival_agent.core.domain import choice_set as choice_set_mod
from arrival_agent.core.domain.choice_set import ChoiceSet
from arrival_agent.core.events import EventType, TripEvent, load_scenario
from arrival_agent.core.tools import eta as eta_mod
from arrival_agent.core.tools import restaurants as restaurants_mod
from arrival_agent.adapters.langgraph.graph import LangGraphArrivalAgent


SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "delayed-flight.json"

# All four match the delayed-flight envelope (cuisines: thai, indian) so the
# filtered pool is 4 -> the stub design takes 3 -> recovery can backfill r4.
FAKE_CANDIDATES = [
    {"restaurant_id": "r1", "restaurant_name": "Lers Ros",
     "categories": ["Thai Restaurant"], "distance_m": 320},
    {"restaurant_id": "r2", "restaurant_name": "Pakwan",
     "categories": ["Indian Restaurant"], "distance_m": 480},
    {"restaurant_id": "r3", "restaurant_name": "Osha",
     "categories": ["Thai Restaurant"], "distance_m": 520},
    {"restaurant_id": "r4", "restaurant_name": "Dosa",
     "categories": ["Indian Restaurant"], "distance_m": 610},
]


def _fake_design(candidates, trip_context, *, past_picks=None, client=None):
    """Deterministic stand-in for the LLM: first three candidates, cuisine axis."""
    options = [
        ChoiceOption(
            option_id=f"opt-{i + 1}",
            restaurant_id=c["restaurant_id"],
            restaurant_name=c["restaurant_name"],
            items=["House special"],
            est_total=20.0 + i,
            cuisine_tags=list(c.get("categories", [])),
            why_this_one=f"stub option {i + 1}",
        )
        for i, c in enumerate(candidates[:3])
    ]
    return ChoiceSet(
        axis=ChoiceAxis.CUISINE,
        axis_reason="stub axis pick",
        options=options,
        why_these="stub set rationale",
    )


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(eta_mod, "estimate_eta", lambda o, d: 16)
    monkeypatch.setattr(
        restaurants_mod, "get_eats_options",
        lambda near, limit=10, **kw: list(FAKE_CANDIDATES),
    )
    monkeypatch.setattr(choice_set_mod, "design_choice_set", _fake_design)
    sc = load_scenario(SCENARIO)
    return LangGraphArrivalAgent(scenario=sc, thread_id="test"), sc


def test_full_delayed_flight_run(agent):
    a, sc = agent
    decisions = [a.handle_event(ev) for ev in sc.events]
    by_type = dict(zip([e.type for e in sc.events], decisions))

    # Early loose-estimate events -> WAIT, with visible reasoning.
    assert by_type[EventType.TRIP_BOOKED].action == Action.WAIT
    assert by_type[EventType.TRIP_BOOKED].reasoning

    # Locate events by type rather than hardcoded indices (scenario order can
    # shift). The first SURFACE is the headline; the order_rejected event drives
    # recovery; check_in re-emits.
    types = [e.type for e in sc.events]
    rej_idx = types.index(EventType.ORDER_REJECTED)

    # The first SURFACE decision designs a 3-option choice set via the stub LLM.
    first_surface = next(d for d in decisions if d.action == Action.SURFACE)
    assert len(first_surface.choice_set) == 3
    assert first_surface.axis == ChoiceAxis.CUISINE
    assert all(o.est_delivery_at is not None for o in first_surface.choice_set)

    # order_rejected while awaiting pick -> recovery: the first option (r1, no
    # restaurant_id in the scenario payload) is swapped for the next-best.
    rej_decision = decisions[rej_idx]
    assert rej_decision.action == Action.SURFACE
    ids = {o.restaurant_id for o in rej_decision.choice_set}
    assert "r1" not in ids, "rejected restaurant should be removed"
    assert "r4" in ids, "next-best candidate should backfill the set"
    assert "went offline" in rej_decision.reasoning

    # check_in while still waiting -> SURFACE re-emitted.
    assert decisions[types.index(EventType.CHECK_IN)].action == Action.SURFACE

    # User picks -> PLACED.
    pick_id = rej_decision.choice_set[0].option_id
    pick = TripEvent(
        type="user_pick",
        at="2026-05-21T00:55:00-07:00",
        payload={"option_id": pick_id},
    )
    placed = a.handle_event(pick)
    assert placed.action == Action.PLACED
    assert placed.placed_option_id == pick_id
    assert "order placed" in placed.reasoning.lower()


def test_state_accumulates_events(agent):
    a, sc = agent
    for ev in sc.events[:3]:
        a.handle_event(ev)
    state = a.state()
    assert len(state["events"]) == 3


def test_no_supply_falls_back_to_breakfast(monkeypatch):
    monkeypatch.setattr(eta_mod, "estimate_eta", lambda o, d: 16)
    monkeypatch.setattr(
        restaurants_mod, "get_eats_options", lambda near, limit=10, **kw: [],
    )
    monkeypatch.setattr(choice_set_mod, "design_choice_set", _fake_design)
    sc = load_scenario(SCENARIO)
    a = LangGraphArrivalAgent(scenario=sc, thread_id="test-nosupply")
    decisions = [a.handle_event(ev) for ev in sc.events[:4]]  # through ride_started
    last = decisions[3]
    assert last.action == Action.SURFACE
    assert len(last.choice_set) == 1
    assert last.choice_set[0].restaurant_id == "breakfast-fallback"
    assert "breakfast" in last.reasoning.lower()


def test_llm_failure_degrades_to_deterministic_options(monkeypatch):
    monkeypatch.setattr(eta_mod, "estimate_eta", lambda o, d: 16)
    monkeypatch.setattr(
        restaurants_mod, "get_eats_options",
        lambda near, limit=10, **kw: list(FAKE_CANDIDATES),
    )

    def _boom(*a, **kw):
        raise ValueError("LLM exploded")

    monkeypatch.setattr(choice_set_mod, "design_choice_set", _boom)
    sc = load_scenario(SCENARIO)
    a = LangGraphArrivalAgent(scenario=sc, thread_id="test-llmfail")
    decisions = [a.handle_event(ev) for ev in sc.events[:4]]
    last = decisions[3]
    assert last.action == Action.SURFACE  # degraded, not dead
    assert len(last.choice_set) == 3
    assert "fell back" in last.reasoning  # the failure is VISIBLE, never silent


def test_envelope_relaxation_is_visible(monkeypatch):
    """Only one candidate matches the envelope cuisines -> agent relaxes and says so."""
    monkeypatch.setattr(eta_mod, "estimate_eta", lambda o, d: 16)
    one_thai = [
        {"restaurant_id": "r1", "restaurant_name": "Nari",
         "categories": ["Thai Restaurant"], "distance_m": 900},
        {"restaurant_id": "r5", "restaurant_name": "Biergarten",
         "categories": ["German Restaurant"], "distance_m": 500},
        {"restaurant_id": "r6", "restaurant_name": "Souvla",
         "categories": ["Greek Restaurant"], "distance_m": 400},
    ]
    monkeypatch.setattr(
        restaurants_mod, "get_eats_options", lambda near, limit=10, **kw: one_thai,
    )
    monkeypatch.setattr(choice_set_mod, "design_choice_set", _fake_design)
    sc = load_scenario(SCENARIO)  # envelope cuisines: thai, indian
    a = LangGraphArrivalAgent(scenario=sc, thread_id="test-relax")
    decisions = [a.handle_event(ev) for ev in sc.events[:4]]
    last = decisions[3]
    assert last.action == Action.SURFACE
    assert "showing nearby alternatives" in last.reasoning
