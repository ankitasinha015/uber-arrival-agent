"""Phase 4 — behaviour memory: what the user does reshapes the next trip's list."""

from __future__ import annotations

from arrival_agent.core.contract import ActionKind, ActionList, Moment
from arrival_agent.core.domain.action_set import curate_actions
from arrival_agent.core.domain.memory import ActionMemory, DROP_THRESHOLD, seed_seasoned


def _delay_list():
    # a delay moment carrying two to-dos: notify hotel + dinner
    return ActionList(
        moment=Moment.DELAY,
        reasoning="two things",
        items=[curate_actions(Moment.DELAY).items[0], curate_actions(Moment.ARRIVAL).items[0]],
    )


def test_new_user_keeps_everything():
    m = ActionMemory("new", in_memory=True)
    shaped = m.shape_actions(Moment.DELAY, _delay_list().items)
    kinds = [i.kind for i in shaped]
    assert ActionKind.NOTIFY_HOTEL in kinds and ActionKind.DINNER in kinds


def test_consistently_dismissed_todo_gets_dropped():
    m = ActionMemory("dismisser", in_memory=True)
    for _ in range(DROP_THRESHOLD):
        m.record(Moment.DELAY, ActionKind.NOTIFY_HOTEL, "decline")
    shaped = m.shape_actions(Moment.DELAY, _delay_list().items)
    kinds = [i.kind for i in shaped]
    assert ActionKind.NOTIFY_HOTEL not in kinds     # learned: they handle it themselves
    assert ActionKind.DINNER in kinds               # but still wants dinner


def test_engagement_protects_a_todo_from_being_dropped():
    m = ActionMemory("mixed", in_memory=True)
    for _ in range(DROP_THRESHOLD + 2):
        m.record(Moment.DELAY, ActionKind.NOTIFY_HOTEL, "decline")
    m.record(Moment.DELAY, ActionKind.NOTIFY_HOTEL, "send")  # once engaged
    shaped = m.shape_actions(Moment.DELAY, _delay_list().items)
    assert ActionKind.NOTIFY_HOTEL in [i.kind for i in shaped]  # not dropped once ever used


def test_affinity_orders_the_list():
    m = ActionMemory("orderer", in_memory=True)
    # dinner picked a lot, hotel used less -> dinner floats first
    for _ in range(3):
        m.record(Moment.DELAY, ActionKind.DINNER, "pick")
    m.record(Moment.DELAY, ActionKind.NOTIFY_HOTEL, "send")
    shaped = m.shape_actions(Moment.DELAY, _delay_list().items)
    assert shaped[0].kind == ActionKind.DINNER


def test_seasoned_traveler_gets_a_shorter_list():
    m = seed_seasoned()
    shaped = m.shape_actions(Moment.DELAY, _delay_list().items)
    kinds = [i.kind for i in shaped]
    assert kinds == [ActionKind.DINNER]             # hotel dropped, dinner kept


def test_curate_actions_uses_memory():
    # the memory plugs straight into the engine's seam
    m = seed_seasoned()
    al = curate_actions(Moment.DELAY, memory=m)
    # DELAY template is just notify_hotel; a seasoned traveler drops it
    assert al.items == []
