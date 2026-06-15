"""The consent beat (ask_first) — Option B / "arrival concierge".

With ask_first on, the agent opens with a single opt-in ASK on the first
late-arrival signal, does NO work until the user says yes, and stays silent if
they never answer. These tests pin the locked behavior:

  1B  trigger: ASK fires once, on the flight_status(delayed) signal.
  2A  silence: no answer => never curates, never surfaces, never places.
  3A  honest-late: a late "yes" still surfaces, with an honest delivery note.
  conformance: LangGraph and raw ASK identically and place the same order;
               the naive baseline never asks (ask_first is a no-op for it).

All I/O stubbed, so the choice set is identical for everyone.
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


def _drive(agent, sc, *, answer=True, consent_idx=1):
    """Drive the timeline. When the agent ASKs (or at consent_idx if forcing a
    late answer), feed a USER_CONSENT event. answer=None => never answer."""
    flight.set_active_scenario(sc)
    metrics.start_run()
    decisions = []
    answered = False
    for i, ev in enumerate(sc.events):
        flight.advance_clock(ev.at)
        d = agent.handle_event(ev)
        decisions.append(d)
        should_answer = answer is not None and not answered and (
            d.action == Action.ASK if consent_idx is None else i == consent_idx
        )
        if should_answer:
            cev = TripEvent(type=EventType.USER_CONSENT, at=ev.at + timedelta(seconds=30),
                            payload={"consent": answer})
            decisions.append(agent.handle_event(cev))
            answered = True
    return decisions


def _pick(agent, option_id, at):
    return agent.handle_event(TripEvent(type=EventType.USER_PICK, at=at,
                                        payload={"option_id": option_id}))


# --- 1B: trigger ---------------------------------------------------------------

def test_ask_fires_once_on_the_delay_signal(stub):
    sc = load_scenario(SCENARIO)
    d = _drive(LangGraphArrivalAgent(sc, thread_id="ask1", ask_first=True), sc, consent_idx=None)
    asks = [i for i, dec in enumerate(d) if dec.action == Action.ASK]
    assert len(asks) == 1                       # exactly once, never re-asked
    # the ask carries a real opt-in prompt for the user
    assert "dinner" in d[asks[0]].ask_prompt.lower()


def test_no_ask_until_a_flight_signal(stub):
    sc = load_scenario(SCENARIO)
    agent = LangGraphArrivalAgent(sc, thread_id="ask2", ask_first=True)
    flight.set_active_scenario(sc)
    metrics.start_run()
    first = agent.handle_event(sc.events[0])    # trip_booked, no flight signal yet
    assert first.action == Action.WAIT          # stays quiet until the flight speaks


# --- 2A: silence ---------------------------------------------------------------

def test_no_answer_means_no_work(stub):
    sc = load_scenario(SCENARIO)
    m = metrics.start_run()
    d = _drive(LangGraphArrivalAgent(sc, thread_id="ask3", ask_first=True), sc, answer=None)
    assert any(dec.action == Action.ASK for dec in d)        # it did ask
    assert all(dec.action != Action.SURFACE for dec in d)    # but never curated
    assert all(dec.action != Action.PLACED for dec in d)     # and never placed
    assert m.llm_calls == 0                                  # no choice-set design


def test_declining_keeps_the_agent_dormant(stub):
    sc = load_scenario(SCENARIO)
    d = _drive(LangGraphArrivalAgent(sc, thread_id="ask4", ask_first=True), sc, answer=False)
    assert any(dec.action == Action.ASK for dec in d)
    assert all(dec.action != Action.SURFACE for dec in d)    # "no" means no
    assert all(dec.action != Action.PLACED for dec in d)


# --- 3A: honest-late -----------------------------------------------------------

def test_late_optin_still_surfaces_with_an_honest_note(stub):
    sc = load_scenario(SCENARIO)
    agent = LangGraphArrivalAgent(sc, thread_id="ask5", ask_first=True)
    flight.set_active_scenario(sc)
    metrics.start_run()
    for ev in sc.events:                        # drive the whole trip, never answering
        flight.advance_clock(ev.at)
        agent.handle_event(ev)
    # opt in AFTER check-in — past the place-by deadline
    late = sc.events[-1].at + timedelta(minutes=5)
    d = agent.handle_event(TripEvent(type=EventType.USER_CONSENT, at=late, payload={"consent": True}))
    assert d.action == Action.SURFACE
    assert "opted in late" in d.reasoning.lower()


# --- conformance ---------------------------------------------------------------

def test_langgraph_and_raw_ask_and_place_identically(stub):
    sc = load_scenario(SCENARIO)
    lg = LangGraphArrivalAgent(sc, thread_id="cfa-lg", ask_first=True)
    raw = RawArrivalAgent(sc, thread_id="cfa-raw", ask_first=True)
    dlg, draw = _drive(lg, sc), _drive(raw, sc)

    # both ask, identically
    alg = next(d for d in dlg if d.action == Action.ASK)
    araw = next(d for d in draw if d.action == Action.ASK)
    assert alg.ask_prompt == araw.ask_prompt

    # both surface the same set after opting in
    slg = next(d for d in dlg if d.action == Action.SURFACE)
    sraw = next(d for d in draw if d.action == Action.SURFACE)
    assert [o.restaurant_id for o in slg.choice_set] == [o.restaurant_id for o in sraw.choice_set]

    # and place the same order
    at = sc.events[-1].at + timedelta(minutes=2)
    plg = _pick(lg, dlg[-1].choice_set[0].option_id, at)
    praw = _pick(raw, draw[-1].choice_set[0].option_id, at)
    assert plg.action == praw.action == Action.PLACED
    assert plg.placed_option_id == praw.placed_option_id


def test_naive_never_asks_even_with_ask_first(stub):
    sc = load_scenario(SCENARIO)
    naive = NaiveArrivalAgent(sc, ask_first=True)   # ask_first is a no-op for the strawman
    flight.set_active_scenario(sc)
    metrics.start_run()
    decisions = [naive.handle_event(ev) for ev in sc.events]
    assert all(d.action != Action.ASK for d in decisions)
