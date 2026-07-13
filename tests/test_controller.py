"""Phase 2 — the controller loop.

Drives the present-next / run-series / pause / check-for-next loop with fake
handlers (no network). Proves: dinner pauses at pick and places on pick; a
restaurant going offline re-pauses with a recovered set; decline skips; and the
loop advances across multiple to-dos ("check for next").
"""

from __future__ import annotations

from arrival_agent.core.contract import (
    ActionItem,
    ActionKind,
    ActionList,
    Moment,
)
from arrival_agent.core.domain.action_set import curate_actions
from arrival_agent.core.domain.choice_set import ChoiceSet
from arrival_agent.core.contract import ChoiceAxis, ChoiceOption
from arrival_agent.core.domain.controller import Done, Pause, TripController
from arrival_agent.core.domain.handlers import (
    DinnerHandler,
    HeadsUpHandler,
    NotifyHotelHandler,
)

FAKE = [
    {"restaurant_id": "r1", "restaurant_name": "Lers Ros", "categories": ["Thai"], "distance_m": 320},
    {"restaurant_id": "r2", "restaurant_name": "Pakwan", "categories": ["Indian"], "distance_m": 480},
    {"restaurant_id": "r3", "restaurant_name": "Osha", "categories": ["Thai"], "distance_m": 520},
    {"restaurant_id": "r4", "restaurant_name": "Dosa", "categories": ["Indian"], "distance_m": 610},
]


def _design(candidates, context):
    options = [
        ChoiceOption(option_id=f"opt-{i+1}", restaurant_id=c["restaurant_id"],
                     restaurant_name=c["restaurant_name"], items=["dish"], est_total=20.0 + i,
                     cuisine_tags=list(c.get("categories", [])), why_this_one=f"o{i+1}")
        for i, c in enumerate(candidates[:3])
    ]
    return ChoiceSet(axis=ChoiceAxis.CUISINE, axis_reason="stub", options=options, why_these="stub")


def _recover(rejected, pool):
    return pool[0] if pool else None


def _dinner_handlers():
    return {
        ActionKind.DINNER: DinnerHandler(
            find=lambda ctx: list(FAKE),
            design=_design,
            place=lambda opt: {"eta": "01:12", "restaurant": opt["restaurant_name"]},
            recover=_recover,
        )
    }


# --- dinner happy path ---------------------------------------------------------

def test_dinner_pauses_at_pick_then_places():
    c = TripController(curate_actions(Moment.ARRIVAL), _dinner_handlers())
    step = c.start()
    assert isinstance(step, Pause)
    assert step.kind == "pick"
    assert 2 <= len(step.payload["options"]) <= 3

    confirm = c.respond({"decision": "pick", "option_id": step.payload["options"][0]["option_id"]})
    assert isinstance(confirm, Pause) and confirm.kind == "confirm_dish"   # suggests the usual dish first
    done = c.respond({"decision": "confirm"})
    assert isinstance(done, Done)
    assert done.outcomes[-1]["outcome"]["placed"] == "Lers Ros"


# --- recovery is just a re-pause ----------------------------------------------

def test_typed_refinement_reshapes_the_options():
    from arrival_agent.web.concierge import parse_intent
    # intent parsing turns free text into a decision
    assert parse_intent("something cheaper please", "pick")["mode"] == "cheaper"
    assert parse_intent("got any ramen?", "pick") == {"decision": "refine", "mode": "cuisine", "term": "ramen", "text": "got any ramen?"}
    assert parse_intent("not hungry", "pick")["decision"] == "decline"

    c = TripController(curate_actions(Moment.ARRIVAL), _dinner_handlers())
    first = c.start()
    prices = [o["est_total"] for o in first.payload["options"]]

    cheaper = c.respond({"decision": "refine", "mode": "cheaper"})
    assert isinstance(cheaper, Pause) and cheaper.kind == "pick"   # still choosing
    got = [o["est_total"] for o in cheaper.payload["options"]]
    assert got == sorted(prices)                                   # reordered cheapest-first
    assert "cheapest" in cheaper.payload["note"]

    c.respond({"decision": "pick", "option_id": cheaper.payload["options"][0]["option_id"]})
    done = c.respond({"decision": "confirm"})
    assert isinstance(done, Done)


def test_offline_restaurant_repauses_with_a_backup():
    c = TripController(curate_actions(Moment.ARRIVAL), _dinner_handlers())
    first = c.start()
    dropped = first.payload["options"][0]["restaurant_id"]

    again = c.respond({"decision": "order_rejected", "restaurant_id": dropped})
    assert isinstance(again, Pause) and again.kind == "pick"      # same to-do, still open
    ids = [o["restaurant_id"] for o in again.payload["options"]]
    assert dropped not in ids                                     # dead option gone
    assert any("Backup" in o["why_this_one"] for o in again.payload["options"])  # backfilled

    confirm = c.respond({"decision": "pick", "option_id": again.payload["options"][0]["option_id"]})
    assert isinstance(confirm, Pause) and confirm.kind == "confirm_dish"
    done = c.respond({"decision": "confirm"})
    assert isinstance(done, Done)


# --- decline skips -------------------------------------------------------------

def test_decline_skips_the_todo():
    c = TripController(curate_actions(Moment.ARRIVAL), _dinner_handlers())
    c.start()
    done = c.respond({"decision": "decline"})
    assert isinstance(done, Done)
    assert done.outcomes[-1]["outcome"] == "declined"


# --- heads-up ------------------------------------------------------------------

def test_heads_up_snooze_completes():
    c = TripController(curate_actions(Moment.DEPARTURE), {ActionKind.HEADS_UP: HeadsUpHandler()})
    step = c.start()
    assert isinstance(step, Pause) and step.kind == "snooze"
    done = c.respond({"decision": "snooze"})
    assert isinstance(done, Done)
    assert done.outcomes[-1]["outcome"] == "acknowledged"


# --- the loop: check for next across multiple to-dos --------------------------

def test_loop_advances_to_the_next_todo():
    # a moment with two to-dos: notify hotel, then dinner
    actions = ActionList(
        moment=Moment.DELAY,
        reasoning="two things to handle",
        items=[
            curate_actions(Moment.DELAY).items[0],     # notify_hotel
            curate_actions(Moment.ARRIVAL).items[0],   # dinner
        ],
    )
    sent = {}
    handlers = {
        ActionKind.NOTIFY_HOTEL: NotifyHotelHandler(send=lambda note: sent.setdefault("note", note) or {"ok": True}),
        **_dinner_handlers(),
    }
    c = TripController(actions, handlers, context={"arrival_hhmm": "1:15 AM"})

    step1 = c.start()
    assert step1.kind == "ask_hotel"                  # first to-do: ASK before notifying
    draft = c.respond({"decision": "yes"})            # yes -> draft the note to send
    assert draft.kind == "send"
    assert "hold my room" in draft.payload["draft"]

    step2 = c.respond({"decision": "send"})           # send -> CHECK FOR NEXT
    assert isinstance(step2, Pause) and step2.kind == "pick"   # advanced to dinner
    assert sent["note"]                                # the hotel note actually went

    c.respond({"decision": "pick", "option_id": step2.payload["options"][0]["option_id"]})  # -> confirm dish
    done = c.respond({"decision": "confirm"})
    assert isinstance(done, Done)
    assert len(done.outcomes) == 2                     # both to-dos resolved
