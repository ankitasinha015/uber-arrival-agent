"""Adapter conformance — the proof behind the framework comparison.

With all I/O stubbed (so the choice set is identical for everyone), the
LangGraph and raw adapters must produce the SAME surfaced choice set and the
SAME terminal decision: they are the same agent, differently orchestrated. The
naive baseline must differ — it surfaces earlier, with one option and no
recovery. This is what lets `--compare` claim "equivalent decisions, different
cost", not just assert it.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from arrival_agent.adapters.langgraph.graph import LangGraphArrivalAgent
from arrival_agent.adapters.naive.loop import NaiveArrivalAgent
from arrival_agent.adapters.raw.loop import RawArrivalAgent
from arrival_agent.core import metrics
from arrival_agent.core.contract import Action, ChoiceAxis, ChoiceOption
from arrival_agent.core.domain import choice_set as choice_set_mod
from arrival_agent.core.domain.choice_set import ChoiceSet
from arrival_agent.core.events import EventType, TripEvent, load_scenario
from arrival_agent.core.tools import eta as eta_mod
from arrival_agent.core.tools import flight
from arrival_agent.core.tools import restaurants as restaurants_mod

SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "delayed-flight.json"

# 4 in-envelope candidates so the set is 3 + a backfill for recovery.
FAKE = [
    {"restaurant_id": "r1", "restaurant_name": "Lers Ros", "categories": ["Thai Restaurant"], "distance_m": 320},
    {"restaurant_id": "r2", "restaurant_name": "Pakwan", "categories": ["Indian Restaurant"], "distance_m": 480},
    {"restaurant_id": "r3", "restaurant_name": "Osha", "categories": ["Thai Restaurant"], "distance_m": 520},
    {"restaurant_id": "r4", "restaurant_name": "Dosa", "categories": ["Indian Restaurant"], "distance_m": 610},
]


def _fake_design(candidates, trip_context, *, past_picks=None, client=None):
    options = [
        ChoiceOption(option_id=f"opt-{i + 1}", restaurant_id=c["restaurant_id"],
                     restaurant_name=c["restaurant_name"], items=["dish"], est_total=20.0 + i,
                     cuisine_tags=list(c.get("categories", [])), why_this_one=f"o{i + 1}")
        for i, c in enumerate(candidates[:3])
    ]
    return ChoiceSet(axis=ChoiceAxis.CUISINE, axis_reason="stub", options=options, why_these="stub set")


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(eta_mod, "estimate_eta", lambda o, d: 16)
    monkeypatch.setattr(restaurants_mod, "get_eats_options", lambda near, limit=10, **kw: list(FAKE))
    monkeypatch.setattr(choice_set_mod, "design_choice_set", _fake_design)


def _drive(agent, sc):
    flight.set_active_scenario(sc)
    metrics.start_run()
    decisions = []
    for ev in sc.events:
        flight.advance_clock(ev.at)
        decisions.append(agent.handle_event(ev))
    return decisions


def _pick(agent, option_id, at):
    return agent.handle_event(TripEvent(type=EventType.USER_PICK, at=at,
                                        payload={"option_id": option_id}))


def test_langgraph_and_raw_surface_the_same_set(stub):
    sc = load_scenario(SCENARIO)
    dlg = _drive(LangGraphArrivalAgent(sc, thread_id="lg"), sc)
    draw = _drive(RawArrivalAgent(sc, thread_id="raw"), sc)

    slg = next(d for d in dlg if d.action == Action.SURFACE)
    sraw = next(d for d in draw if d.action == Action.SURFACE)
    assert [o.restaurant_id for o in slg.choice_set] == [o.restaurant_id for o in sraw.choice_set]
    assert slg.axis == sraw.axis == ChoiceAxis.CUISINE

    # final parked set (after order_rejected recovery) must match too
    assert [o.restaurant_id for o in dlg[-1].choice_set] == [o.restaurant_id for o in draw[-1].choice_set]


def test_langgraph_and_raw_place_the_same_order(stub):
    sc = load_scenario(SCENARIO)
    lg = LangGraphArrivalAgent(sc, thread_id="lg2")
    raw = RawArrivalAgent(sc, thread_id="raw2")
    dlg, draw = _drive(lg, sc), _drive(raw, sc)
    at = sc.events[-1].at + timedelta(minutes=2)

    plg = _pick(lg, dlg[-1].choice_set[0].option_id, at)
    praw = _pick(raw, draw[-1].choice_set[0].option_id, at)
    assert plg.action == praw.action == Action.PLACED
    assert plg.placed_option_id == praw.placed_option_id


def test_naive_differs_from_the_smart_agents(stub):
    sc = load_scenario(SCENARIO)
    naive = NaiveArrivalAgent(sc)
    d = _drive(naive, sc)

    # naive surfaces at ride_started (index 3), not ride_ended
    surface_idx = next(i for i, dec in enumerate(d) if dec.action == Action.SURFACE)
    assert sc.events[surface_idx].type == EventType.RIDE_STARTED

    surface = d[surface_idx]
    assert len(surface.choice_set) == 1            # one option, no real choice
    assert surface.axis is None                    # no axis design
    # naive ignores order_rejected (no recovery) — still one option after it
    assert all(dec.action != Action.PLACED for dec in d)  # parked, awaiting pick


def test_naive_makes_no_llm_call(stub):
    sc = load_scenario(SCENARIO)
    m = metrics.start_run()
    naive = NaiveArrivalAgent(sc)
    flight.set_active_scenario(sc)
    for ev in sc.events:
        flight.advance_clock(ev.at)
        naive.handle_event(ev)
    assert m.llm_calls == 0  # the headline contrast: no choice-set design
