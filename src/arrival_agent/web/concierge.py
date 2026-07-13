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
from arrival_agent.core.domain.intensity import Intensity, assess, read
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


# --- arrival: the city welcome, airport-exit time, and cuisine-ranked dinner ---

CITY = "San Francisco"
AIRPORT_EXIT_MIN = 35   # deplane + bags (would be a live/airport feed in prod)

# The user's Uber Eats order preference — favourite cuisines first (mocked; in a
# real Uber build this is first-party order history).
_UBER_EATS_PREF = ["Ramen", "Mexican", "Thai", "Burger", "American", "Pizza"]

# Cuisine-varied places near the hotel (mocked feed).
_ARRIVAL_RESTAURANTS = [
    {"restaurant_id": "a-ippudo", "restaurant_name": "Ippudo", "cuisine": "Ramen", "est_total": 19, "items": ["Tonkotsu Ramen"]},
    {"restaurant_id": "a-tropi", "restaurant_name": "Tropisueño", "cuisine": "Mexican", "est_total": 24, "items": ["Carnitas Tacos"]},
    {"restaurant_id": "a-super", "restaurant_name": "Super Duper Burgers", "cuisine": "Burger", "est_total": 16, "items": ["Burger, Fries"]},
    {"restaurant_id": "a-grove", "restaurant_name": "The Grove", "cuisine": "American", "est_total": 22, "items": ["Roast Chicken"]},
    {"restaurant_id": "a-osha", "restaurant_name": "Osha Thai", "cuisine": "Thai", "est_total": 21, "items": ["Pad See Ew"]},
]


def _arrival_find(context):
    return list(_ARRIVAL_RESTAURANTS)


def _arrival_design(candidates, context):
    """Rank places near the hotel by the cuisines the user orders most on Uber
    Eats, mark their usual, and show the range of cuisines available."""
    rank = {c: i for i, c in enumerate(_UBER_EATS_PREF)}
    ordered = sorted(candidates, key=lambda r: rank.get(r.get("cuisine"), 99))
    options = []
    for i, r in enumerate(ordered[:4]):
        usual = i == 0
        why = (f"your usual — you order {r['cuisine'].lower()} most trips" if usual
               else f"{r['cuisine']} · near your hotel")
        o = ChoiceOption(
            option_id=f"opt-{i + 1}", restaurant_id=r["restaurant_id"],
            restaurant_name=r["restaurant_name"], items=list(r["items"]),
            est_total=float(r["est_total"]), cuisine_tags=[r["cuisine"]],
            why_this_one=why,
        )
        o.est_delivery_at = context.get("deliver_at", _DELIVER)
        options.append(o)

    class _CS:
        pass
    cs = _CS()
    cs.options, cs.axis = options, ChoiceAxis.CUISINE
    cs.why_these = "ranked by the cuisines you order most on Uber Eats"
    cs.lead = f"Want to sort dinner? Here are places near {_HOTEL.split(',')[0]}, by the cuisines you usually order:"
    return cs


# Situation feeds per mode (mocked, real-shaped) — these drive the intensity dial.
_SIGNALS = {
    "new":      {"delay_min": 45, "arrival_hour": 1,  "security_wait_min": 45, "pre_flight_min": 120, "security_fresh": True},
    "seasoned": {"delay_min": 45, "arrival_hour": 1,  "security_wait_min": 45, "pre_flight_min": 120, "security_fresh": True},
    "smooth":   {"delay_min": 0,  "arrival_hour": 21, "security_wait_min": 8,  "pre_flight_min": 120, "security_fresh": True},
}

_DEP_INTRO_HIGH = "Before you head out — security's running long right now. Leave sooner:"
_DEP_INTRO_LOW = "Before you head out — one thing worth doing:"
_GATE_HOTEL_INTRO = ("Hours later, at the gate — your flight slipped 45 min, so you'll land around "
                     "1:12 AM. Let me give the front desk a heads-up so they hold your room:")
_WELCOME = f"Welcome to {CITY} 👋"
_EXIT_LINE = (f"You're about {AIRPORT_EXIT_MIN} min from being out of the airport "
              f"(deplane, then bags) — in your room by ~1:12 AM.")
_SMOOTH_ARRIVAL = [f"Welcome to {CITY} 👋",
                   "You're in early tonight — everything's on track, kitchens are open and the "
                   "line was clear. One optional thing, then I'll leave you be:"]


def _departure_segment(sig, memory):
    """Fires only if the dial says so (long-enough line, in the window, fresh).
    The message is driven by the actual wait, not generic copy."""
    level = assess(Moment.DEPARTURE, sig)
    if level == Intensity.NONE:
        return None
    al = curate_actions(Moment.DEPARTURE, signals=sig, memory=memory)
    if not al.items:
        return None
    wait = sig.get("security_wait_min")
    lead = 45 if level == Intensity.HIGH else 30   # urgent line → leave even earlier
    for it in al.items:
        if it.kind == ActionKind.HEADS_UP:
            it.title = f"Leave ~{lead} min earlier"
            it.detail = (f"Security's running about {wait} min right now — "
                         f"give yourself an extra {lead} minutes to make the gate.")
    intro = _DEP_INTRO_HIGH if level == Intensity.HIGH else _DEP_INTRO_LOW
    return (intro, al)


def _hotel_list(memory):
    items = [curate_actions(Moment.DELAY).items[0]]  # notify_hotel
    if memory is not None:
        items = list(memory.shape_actions(Moment.DELAY, items))
    return items


def _segments(memory, mode: str) -> list:
    """The trip as a sequence of (intro, ActionList) moments, sized by the dial.
    intro may be a list of lines (the arrival welcome is several agent turns)."""
    sig = _SIGNALS.get(mode, _SIGNALS["new"])
    segs = []

    dep = _departure_segment(sig, memory)
    if dep:
        segs.append(dep)

    if assess(Moment.ARRIVAL, sig) == Intensity.HIGH:
        # at the gate: hold the room (a seasoned traveler handles it themselves,
        # so memory drops it and this segment is skipped)
        hotel = _hotel_list(memory)
        if hotel:
            segs.append((_GATE_HOTEL_INTRO, ActionList(
                moment=Moment.DELAY, reasoning="hold the room", items=hotel,
                intensity="high", read=read(Moment.DELAY, sig))))
        # on arrival: welcome + airport-exit time + cuisine-ranked dinner
        segs.append(([_WELCOME, _EXIT_LINE], ActionList(
            moment=Moment.ARRIVAL, reasoning="dinner near the hotel",
            items=[curate_actions(Moment.ARRIVAL).items[0]], intensity="high", read="")))
    else:
        # calm arrival: welcome + one optional hotel offer, no dinner
        segs.append((_SMOOTH_ARRIVAL, ActionList(
            moment=Moment.DELAY, reasoning="all good", items=_hotel_list(memory),
            intensity="low", read="")))
    return segs


def _handlers():
    return {
        ActionKind.HEADS_UP: HeadsUpHandler(),
        ActionKind.NOTIFY_HOTEL: NotifyHotelHandler(
            send=lambda note: send_hotel_note(_HOTEL, note),
        ),
        ActionKind.DINNER: DinnerHandler(
            find=_arrival_find,
            design=_arrival_design,
            place=orders_mod.place_order,
            recover=recover_from_rejection,
        ),
    }


def _trip_context(mode: str) -> dict:
    """The facts the agent pulled — shown at the top so you see its inputs."""
    sig = _SIGNALS.get(mode, _SIGNALS["new"])
    arrival = "~9:40 PM (on time)" if mode == "smooth" else "~1:12 AM (delayed 45m)"
    return {
        "flight": "UA 517", "route": "EWR → SFO", "hotel": "Hotel Zephyr, San Francisco",
        "arrival": arrival,
        "security_min": sig.get("security_wait_min"),
        "delay_min": sig.get("delay_min", 0),
        "source": "from your booking email",
    }


def _context(mode: str = "new") -> dict:
    arrival_hhmm = "9:40 PM" if mode == "smooth" else "1:15 AM"
    return {"arrival_hhmm": arrival_hhmm, "city": _HOTEL, "deliver_at": _DELIVER,
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
    mode: str = "new"
    queue: asyncio.Queue | None = None
    response: asyncio.Future | None = None
    started: bool = False
    awaiting: bool = False
    current: Pause | None = None  # the pause the user is answering (for say())


class ConciergeRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, ConciergeRun] = {}

    def create(self, mode: str = "new") -> ConciergeRun:
        if mode not in _SIGNALS:
            mode = "new"
        memory = seed_seasoned() if mode == "seasoned" else None
        run = ConciergeRun(
            run_id=uuid4().hex[:12], segments=_segments(memory, mode), mode=mode
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
        await run.queue.put(("context", _trip_context(run.mode)))
        for intro, actions in run.segments:
            if getattr(actions, "read", ""):   # show the signals -> verdict (data flow)
                await run.queue.put(("read", {"text": actions.read, "intensity": actions.intensity}))
            for line in (intro if isinstance(intro, list) else [intro]):
                await run.queue.put(("agent", {"text": line}))
            controller = TripController(actions, _handlers(), _context(run.mode))
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
