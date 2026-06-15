"""Phase 1 — the action-list model + curate engine.

curate_actions turns a moment into an ordered list of to-dos, each a series of
steps with explicit pause points. Memory (optional) reshapes the list. Pure, no
I/O — these run instantly with no stubs.
"""

from __future__ import annotations

from arrival_agent.core.contract import ActionItem, ActionKind, ActionList, Moment
from arrival_agent.core.domain.action_set import curate_actions


def test_each_moment_curates_its_todo():
    assert curate_actions(Moment.DEPARTURE).items[0].kind == ActionKind.HEADS_UP
    assert curate_actions(Moment.DELAY).items[0].kind == ActionKind.NOTIFY_HOTEL
    assert curate_actions(Moment.ARRIVAL).items[0].kind == ActionKind.DINNER


def test_todos_carry_a_series_with_a_pause():
    dinner = curate_actions(Moment.ARRIVAL).items[0]
    # the agent runs auto steps and stops at the user's pick
    assert [s.name for s in dinner.steps][0] == "find what's open near the hotel"
    pause = dinner.next_pause()
    assert pause is not None and pause.pause_for == "pick"


def test_notify_hotel_pauses_on_send():
    hotel = curate_actions(Moment.DELAY).items[0]
    assert hotel.next_pause().pause_for == "send"
    # draft happens before the pause, confirm after
    names = [s.name for s in hotel.steps]
    assert names.index("draft late-arrival note") < names.index("send") < names.index("confirm sent")


def test_action_list_walks_pending():
    al = curate_actions(Moment.ARRIVAL)
    nxt = al.next_pending()
    assert nxt is not None and nxt.status == "proposed"
    nxt.status = "done"
    assert al.next_pending() is None      # nothing left once the only to-do is done


def test_reasoning_names_the_todos():
    r = curate_actions(Moment.DELAY).reasoning
    assert "delay" in r and "notify hotel" in r.lower()


# --- memory reshaping ----------------------------------------------------------

class _DropEverything:
    def shape_actions(self, moment, items):
        return []  # user dismisses everything for this moment


class _Reverse:
    def shape_actions(self, moment, items):
        return list(reversed(items))


def test_memory_can_drop_todos():
    al = curate_actions(Moment.ARRIVAL, memory=_DropEverything())
    assert al.items == []
    assert al.next_pending() is None


def test_memory_reshapes_without_breaking_the_model():
    base = curate_actions(Moment.ARRIVAL)
    shaped = curate_actions(Moment.ARRIVAL, memory=_Reverse())
    assert isinstance(shaped, ActionList)
    assert {i.kind for i in shaped.items} == {i.kind for i in base.items}
