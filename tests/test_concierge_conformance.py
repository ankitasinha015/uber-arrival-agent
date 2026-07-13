"""Phase 7 — controller driver parity.

The V3 controller is pure core, so a raw loop and a LangGraph interrupt graph
must drive it to the SAME pauses and the SAME outcomes. This is the V3 version of
the ArrivalAgent conformance proof: equivalent behavior, different orchestration.
"""

from __future__ import annotations

from arrival_agent.adapters.concierge_drivers import drive_langgraph, drive_raw
from arrival_agent.core.contract import (
    ActionKind, ActionList, ChoiceAxis, ChoiceOption, Moment,
)
from arrival_agent.core.domain.action_set import curate_actions
from arrival_agent.core.domain.choice_set import ChoiceSet
from arrival_agent.core.domain.controller import TripController
from arrival_agent.core.domain.handlers import DinnerHandler, NotifyHotelHandler

FAKE = [
    {"restaurant_id": "r1", "restaurant_name": "Lers Ros", "categories": ["Thai"]},
    {"restaurant_id": "r2", "restaurant_name": "Pakwan", "categories": ["Indian"]},
    {"restaurant_id": "r3", "restaurant_name": "Osha", "categories": ["Thai"]},
    {"restaurant_id": "r4", "restaurant_name": "Dosa", "categories": ["Indian"]},
]


def _design(candidates, context):
    opts = [ChoiceOption(option_id=f"opt-{i+1}", restaurant_id=c["restaurant_id"],
                         restaurant_name=c["restaurant_name"], items=["dish"], est_total=20.0 + i,
                         cuisine_tags=list(c.get("categories", [])), why_this_one=f"o{i+1}")
            for i, c in enumerate(candidates[:3])]
    return ChoiceSet(axis=ChoiceAxis.CUISINE, axis_reason="stub", options=opts, why_these="stub")


def _factory():
    """A fresh delay-moment controller (notify hotel + dinner) each call —
    deterministic, so LangGraph's replay reaches the same state."""
    actions = ActionList(
        moment=Moment.DELAY, reasoning="two things",
        items=[curate_actions(Moment.DELAY).items[0], curate_actions(Moment.ARRIVAL).items[0]],
    )
    handlers = {
        ActionKind.NOTIFY_HOTEL: NotifyHotelHandler(send=lambda note: {"ok": True}),
        ActionKind.DINNER: DinnerHandler(
            find=lambda ctx: list(FAKE), design=_design,
            place=lambda o: {"eta": "01:12"},
            recover=lambda rej, pool: pool[0] if pool else None,
        ),
    }
    return TripController(actions, handlers, {"arrival_hhmm": "1:15 AM"})


def _responder_happy(pause: dict) -> dict:
    if pause["kind"] == "send":
        return {"decision": "send"}
    if pause["kind"] == "confirm_dish":                          # accept the suggested dish
        return {"decision": "confirm"}
    return {"decision": "pick", "option_id": pause["payload"]["options"][0]["option_id"]}


def _responder_with_recovery(pause: dict) -> dict:
    # decline no; send the note; on the first dinner pause report offline, then pick
    if pause["kind"] == "send":
        return {"decision": "send"}
    if pause["kind"] == "confirm_dish":
        return {"decision": "confirm"}
    opts = pause["payload"]["options"]
    if any("Backup" in o["why_this_one"] for o in opts):        # this is the recovered set
        return {"decision": "pick", "option_id": opts[0]["option_id"]}
    return {"decision": "order_rejected", "restaurant_id": opts[0]["restaurant_id"]}


def _outcome_shape(outcomes):
    # compare on stable fields (ignore mock order ids)
    out = []
    for o in outcomes:
        v = o["outcome"]
        out.append(v.get("placed") if isinstance(v, dict) else v)
    return out


def test_raw_and_langgraph_are_identical_happy_path():
    praw, oraw = drive_raw(_factory, _responder_happy)
    plg, olg = drive_langgraph(_factory, _responder_happy, thread_id="happy")
    assert praw == plg == ["send", "pick", "confirm_dish"]
    assert _outcome_shape(oraw) == _outcome_shape(olg)


def test_raw_and_langgraph_are_identical_through_recovery():
    praw, oraw = drive_raw(_factory, _responder_with_recovery)
    plg, olg = drive_langgraph(_factory, _responder_with_recovery, thread_id="recover")
    # send, then a pick that's rejected, then a pick on the recovered set, then confirm the dish
    assert praw == plg == ["send", "pick", "pick", "confirm_dish"]
    assert _outcome_shape(oraw) == _outcome_shape(olg)
    # both actually placed a dinner order
    assert any(isinstance(o["outcome"], dict) and o["outcome"].get("placed") for o in oraw)
