"""V3 web integration — drive the TripController over SSE for the assistant thread.

This is the concierge demo (separate from the ask-beat demo). It builds a moment's
to-do list, wires the controller's handlers to the real tools (with deterministic
fallbacks so it renders in replay with no keys), and streams each pause to the
browser. The frontend renders the assistant thread; /respond feeds the user's
pick/send/snooze back into the controller.

One moment for the demo: a delayed flight surfaces two to-dos — notify the hotel,
then dinner — so the whole loop (present next -> pause -> check for next ->
recovery) shows on one screen.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from arrival_agent.core.contract import (
    ActionKind,
    ActionList,
    ChoiceAxis,
    ChoiceOption,
    Moment,
)
from arrival_agent.core.domain import choice_set as choice_set_mod
from arrival_agent.core.domain.action_set import curate_actions
from arrival_agent.core.domain.controller import Done, Pause, TripController
from arrival_agent.core.domain.handlers import DinnerHandler, NotifyHotelHandler
from arrival_agent.core.domain.memory import seed_seasoned
from arrival_agent.core.tools import orders as orders_mod
from arrival_agent.core.tools import restaurants as restaurants_mod
from arrival_agent.core.tools.email import send_hotel_note
from arrival_agent.core.domain.recovery import recover_from_rejection

_CLOSE = object()
_HOTEL = "Hotel Zephyr, San Francisco"
_ARRIVAL = datetime(2026, 5, 21, 1, 12, tzinfo=timezone(timedelta(hours=-7)))
_DELIVER = _ARRIVAL + timedelta(minutes=20)

# Deterministic candidates for when the live/recorded restaurants tool isn't
# available (the concierge flow isn't in the replay cache). Honest fallback,
# same pattern as the choice-set fallback below.
_FALLBACK_RESTAURANTS = [
    {"restaurant_id": "f-ippudo", "restaurant_name": "Ippudo", "categories": ["Ramen"], "distance_m": 300},
    {"restaurant_id": "f-super", "restaurant_name": "Super Duper Burgers", "categories": ["Burger"], "distance_m": 350},
    {"restaurant_id": "f-tropi", "restaurant_name": "Tropisueno", "categories": ["Mexican"], "distance_m": 420},
    {"restaurant_id": "f-grove", "restaurant_name": "The Grove", "categories": ["American"], "distance_m": 500},
]


def _find(context):
    """Open places near the hotel — recorded/live if available, else deterministic."""
    try:
        results = restaurants_mod.get_eats_options(_HOTEL, limit=10)
        return results or _FALLBACK_RESTAURANTS
    except Exception:
        return _FALLBACK_RESTAURANTS


def _design(candidates, context):
    """Design the choice set. Try the LLM (cache-backed in replay); fall back to
    a deterministic set so the demo always renders."""
    deliver = context.get("deliver_at", _DELIVER)
    try:
        cs = choice_set_mod.design_choice_set(candidates[:8], context)
        options, axis, why = cs.options, cs.axis, cs.why_these
    except Exception:
        options = [
            ChoiceOption(
                option_id=f"opt-{i + 1}", restaurant_id=c["restaurant_id"],
                restaurant_name=c["restaurant_name"], items=["Chef's pick"],
                est_total=18.0 + 3 * i, cuisine_tags=list(c.get("categories", [])),
                why_this_one="Open now, close to your hotel",
            )
            for i, c in enumerate(candidates[:3])
        ]
        axis, why = ChoiceAxis.SPEED_VS_QUALITY, "Fast comfort vs a real late-night meal."
    for o in options:
        o.est_delivery_at = deliver

    class _CS:
        pass
    cs = _CS()
    cs.options, cs.axis, cs.why_these = options, axis, why
    return cs


def _build_actions(memory=None) -> ActionList:
    """The delay moment for the demo: notify hotel, then dinner. Behaviour memory
    (a returning traveler) can drop/reorder — a seasoned traveler who always
    handles the hotel themselves gets just dinner."""
    items = [
        curate_actions(Moment.DELAY).items[0],     # notify_hotel
        curate_actions(Moment.ARRIVAL).items[0],   # dinner
    ]
    if memory is not None:
        items = list(memory.shape_actions(Moment.DELAY, items))
    return ActionList(
        moment=Moment.DELAY,
        reasoning="a delayed flight puts two things at risk: the room hold and a late-night meal",
        items=items,
    )


def _handlers():
    return {
        ActionKind.NOTIFY_HOTEL: NotifyHotelHandler(
            send=lambda note: send_hotel_note(_HOTEL, note),
        ),
        ActionKind.DINNER: DinnerHandler(
            find=_find,
            design=_design,
            place=orders_mod.place_order,
            recover=recover_from_rejection,
        ),
    }


@dataclass
class ConciergeRun:
    run_id: str
    controller: TripController
    seasoned: bool = False
    queue: asyncio.Queue | None = None
    response: asyncio.Future | None = None
    started: bool = False
    awaiting: bool = False


class ConciergeRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, ConciergeRun] = {}

    def create(self, seasoned: bool = False) -> ConciergeRun:
        memory = seed_seasoned() if seasoned else None
        controller = TripController(
            _build_actions(memory), _handlers(),
            context={"arrival_hhmm": "1:15 AM", "city": _HOTEL, "deliver_at": _DELIVER,
                     "time_of_day": f"{_ARRIVAL:%H:%M} (room arrival estimate)",
                     "fatigue": "high late-night arrival after a flight"},
        )
        run = ConciergeRun(run_id=uuid4().hex[:12], controller=controller, seasoned=seasoned)
        self._runs[run.run_id] = run
        return run

    def get(self, run_id: str) -> ConciergeRun | None:
        return self._runs.get(run_id)

    def submit(self, run_id: str, user_input: dict) -> bool:
        run = self._runs.get(run_id)
        if run is None or not run.awaiting or run.response is None or run.response.done():
            return False
        run.response.set_result(user_input)
        return True

    def discard(self, run_id: str) -> None:
        self._runs.pop(run_id, None)


registry = ConciergeRegistry()


def _pause_payload(step: Pause) -> dict:
    return {"action_id": step.action_id, "kind": step.kind, "title": step.title, "payload": step.payload}


async def drive(run: ConciergeRun) -> None:
    """Run the controller, streaming each agent turn and pause to the browser."""
    loop = asyncio.get_running_loop()
    if run.queue is None:
        run.queue = asyncio.Queue()
    try:
        if run.seasoned:
            opening = (
                "Welcome back. Your flight slipped 45 min — you'll reach your room around "
                "1:12 AM. You usually sort the hotel yourself, so I'll just line up dinner:"
            )
        else:
            opening = (
                "Your flight slipped 45 min — you'll reach your room around 1:12 AM, "
                "and kitchens near Hotel Zephyr close soon. A couple of things worth handling:"
            )
        await run.queue.put(("agent", {"text": opening}))
        step = await asyncio.to_thread(run.controller.start)
        while isinstance(step, Pause):
            await run.queue.put(("todo", _pause_payload(step)))
            run.response = loop.create_future()
            run.awaiting = True
            user_input = await run.response
            run.awaiting = False
            await run.queue.put(("you", {"action_id": step.action_id, "decision": user_input.get("decision")}))
            step = await asyncio.to_thread(run.controller.respond, user_input)
        await run.queue.put(("done", {"outcomes": step.outcomes}))
    except Exception as e:  # never hang the stream
        await run.queue.put(("error", {"message": f"{type(e).__name__}: {e}"}))
    finally:
        await run.queue.put((_CLOSE, None))
        registry.discard(run.run_id)
