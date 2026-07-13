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
from arrival_agent.core.domain.handlers import DinnerHandler, HeadsUpHandler, NotifyHotelHandler
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
    # Clean, JSON-serializable context for the LLM/cache layer (a datetime in the
    # key would break record/replay matching). deliver_at is stamped separately.
    llm_context = {
        "time_of_day": context.get("time_of_day", f"{_ARRIVAL:%H:%M} (room arrival estimate)"),
        "city": context.get("city", _HOTEL),
        "fatigue": context.get("fatigue", "high late-night arrival after a flight"),
    }
    try:
        cs = choice_set_mod.design_choice_set(candidates[:8], llm_context)
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


def _departure_actions(memory=None) -> ActionList:
    """Before the trip: the peak-season security heads-up (shown light)."""
    return curate_actions(Moment.DEPARTURE, memory=memory)


def _delay_actions(memory=None) -> ActionList:
    """The delay moment: notify hotel, then dinner. Behaviour memory (a returning
    traveler) can drop/reorder — one who handles the hotel themselves gets just
    dinner."""
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


_DEP_INTRO = ("Before you head out — it's peak travel season and security lines are "
              "heavy today. One thing worth doing now:")
_DELAY_INTRO_NEW = ("Hours later, at the gate — your flight just slipped 45 min. You'll reach "
                    "your room around 1:12 AM, and kitchens near Hotel Zephyr close soon. "
                    "A couple of things worth handling:")
_DELAY_INTRO_SEASONED = ("Welcome back. Your flight slipped 45 min — you'll reach your room around "
                         "1:12 AM. You usually sort the hotel yourself, so I'll just line up dinner:")


def _segments(memory, seasoned: bool) -> list:
    """The trip as a sequence of (intro, ActionList) moments — one engine, many
    moments. Segments whose list is empty (all dropped by memory) are skipped."""
    segs = []
    dep = _departure_actions(memory)
    if dep.items:
        segs.append((_DEP_INTRO, dep))
    segs.append(((_DELAY_INTRO_SEASONED if seasoned else _DELAY_INTRO_NEW), _delay_actions(memory)))
    return segs


def _handlers():
    return {
        ActionKind.HEADS_UP: HeadsUpHandler(),
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


def _context() -> dict:
    return {"arrival_hhmm": "1:15 AM", "city": _HOTEL, "deliver_at": _DELIVER,
            "time_of_day": f"{_ARRIVAL:%H:%M} (room arrival estimate)",
            "fatigue": "high late-night arrival after a flight"}


_CUISINES = ["ramen", "noodle", "thai", "mexican", "burger", "pizza", "sushi",
             "indian", "asian", "chinese", "italian", "american", "vegetarian", "vegan"]
_SKIP = ("skip", "no thanks", "not hungry", "nothing", "cancel", "don't", "stop", "nope")
_CHEAP = ("cheap", "cheaper", "budget", "less", "inexpensive")
_OTHER = ("other", "different", "else", "more", "again", "another")


def parse_intent(text: str, kind: str) -> dict:
    """Turn free text into a decision the controller understands. Rules now; an
    LLM would slot in here at scale. Always carries the raw text for the echo."""
    t = (text or "").lower().strip()
    if any(w in t for w in _SKIP):
        return {"decision": "decline", "text": text}
    if kind == "pick":
        if any(w in t for w in _CHEAP):
            return {"decision": "refine", "mode": "cheaper", "text": text}
        for cz in _CUISINES:
            if cz in t:
                return {"decision": "refine", "mode": "cuisine", "term": cz, "text": text}
        if any(w in t for w in _OTHER):
            return {"decision": "refine", "mode": "other", "text": text}
        return {"decision": "refine", "mode": "unknown", "text": text}
    if kind == "send" and any(w in t for w in ("send", "yes", "go ahead", "do it", "ok", "sure")):
        return {"decision": "send", "text": text}
    if kind == "snooze" and any(w in t for w in ("got it", "ok", "sure", "thanks")):
        return {"decision": "snooze", "text": text}
    return {"decision": "refine", "text": text}  # stray text -> handler re-pauses with a hint


@dataclass
class ConciergeRun:
    run_id: str
    segments: list  # [(intro_text, ActionList)] — the trip's moments in order
    seasoned: bool = False
    queue: asyncio.Queue | None = None
    response: asyncio.Future | None = None
    started: bool = False
    awaiting: bool = False
    current: Pause | None = None  # the pause the user is answering (for say())


class ConciergeRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, ConciergeRun] = {}

    def create(self, seasoned: bool = False) -> ConciergeRun:
        memory = seed_seasoned() if seasoned else None
        run = ConciergeRun(
            run_id=uuid4().hex[:12], segments=_segments(memory, seasoned), seasoned=seasoned
        )
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

    def say(self, run_id: str, text: str) -> bool:
        """The user typed something. Interpret it against the current pause and
        feed the resulting decision into the controller."""
        run = self._runs.get(run_id)
        if run is None or not run.awaiting or run.current is None:
            return False
        return self.submit(run_id, parse_intent(text, run.current.kind))

    def discard(self, run_id: str) -> None:
        self._runs.pop(run_id, None)


registry = ConciergeRegistry()


def _pause_payload(step: Pause) -> dict:
    return {"action_id": step.action_id, "kind": step.kind, "title": step.title, "payload": step.payload}


async def drive(run: ConciergeRun) -> None:
    """Walk the trip's moments in order. Each moment gets its own controller — one
    engine, many moments — streaming agent turns and pauses to the browser."""
    loop = asyncio.get_running_loop()
    if run.queue is None:
        run.queue = asyncio.Queue()
    outcomes: list[dict] = []
    try:
        for intro, actions in run.segments:
            await run.queue.put(("agent", {"text": intro}))
            controller = TripController(actions, _handlers(), _context())
            step = await asyncio.to_thread(controller.start)
            while isinstance(step, Pause):
                await run.queue.put(("todo", _pause_payload(step)))
                run.response = loop.create_future()
                run.awaiting = True
                run.current = step
                user_input = await run.response
                run.awaiting = False
                run.current = None
                await run.queue.put(("you", {
                    "action_id": step.action_id,
                    "decision": user_input.get("decision"),
                    "text": user_input.get("text"),
                }))
                step = await asyncio.to_thread(controller.respond, user_input)
            outcomes.extend(step.outcomes)  # step is Done for this moment
        await run.queue.put(("done", {"outcomes": outcomes}))
    except Exception as e:  # never hang the stream
        await run.queue.put(("error", {"message": f"{type(e).__name__}: {e}"}))
    finally:
        await run.queue.put((_CLOSE, None))
        registry.discard(run.run_id)
