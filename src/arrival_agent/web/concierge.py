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
import os
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
from arrival_agent.web import concierge_store as store

_CLOSE = object()
_HOTEL = "Hotel Zephyr, San Francisco"  # display name (notes, welcome copy)
# Precise address for GEOCODING. "Hotel Zephyr, San Francisco" alone is too vague
# — Mapbox resolves it 25 km away in the East Bay. The full street address pins it
# to Fisherman's Wharf so "nearby" restaurants are actually nearby.
_HOTEL_ADDRESS = "Hotel Zephyr, 250 Beach St, San Francisco, CA 94133"
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
        results = restaurants_mod.get_eats_options(_HOTEL_ADDRESS, limit=10)
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

AIRPORT_EXIT_MIN = 35        # domestic: deplane + baggage claim
INTL_EXIT_MIN = 80           # international: + passport control/immigration + customs
RIDE_TO_HOTEL_MIN = 15       # airport → hotel, rough

# Non-US arrival airports — an arrival here (from a US origin) is international, so
# the traveler clears immigration + customs, which runs long. (Would be a real
# airport/immigration feed in prod.)
_INTL_AIRPORTS = {"BER", "LHR", "CDG", "FRA", "AMS", "MAD", "FCO", "NRT", "HND",
                  "ICN", "SIN", "HKG", "DXB", "YYZ", "MEX", "GRU", "SYD"}


def _is_international(route: str) -> bool:
    """route like 'JFK → BER' — international if the arrival airport is outside the US."""
    dest = route.split("→")[-1].strip() if route else ""
    return dest in _INTL_AIRPORTS

# The user's Uber Eats taste profile — favourite cuisines first. This is behavior
# that travels WITH you (built from order history across cities), NOT a "usual
# restaurant" in a place you've never been. In a real Uber build it's first-party
# order history; here it's a mocked ordering of cuisines.
_UBER_EATS_PREF = ["Ramen", "Mexican", "Thai", "Burger", "American", "Pizza"]

# How Foursquare's category names map onto the user's taste cuisines. Checked in
# _UBER_EATS_PREF order, so the earliest (strongest) preference wins a match.
# NOTE: the 'American' bucket used to include bbq/barbecue/grill/steak — weak signals
# that mis-bucketed 'Korean BBQ', 'Bar & Grill', etc. as American (error-analysis
# finding: cuisine-misclassification). Now American takes strong signals only.
_CUISINE_ALIASES = {
    "Ramen": ["ramen", "noodle", "japanese"],
    "Mexican": ["mexican", "taqueria", "taco", "tex-mex"],
    "Thai": ["thai"],
    "Burger": ["burger"],
    "American": ["american", "diner", "comfort", "steakhouse", "gastropub"],
    "Pizza": ["pizza", "pizzeria", "italian"],
}

# The traveler's MOST-ORDERED dish per cuisine, from Uber Eats history. When they
# pick a place of that cuisine, the agent offers to re-order their go-to (in a real
# Uber build these come straight from order history; here they're mocked). Honest:
# it's the dish you order most in this cuisine, fetched from THIS restaurant — not a
# claim you've ordered at this specific spot before.
_MOST_ORDERED_DISH = {
    "Ramen": "Tonkotsu Ramen", "Mexican": "Carnitas Burrito", "Thai": "Pad Thai",
    "Burger": "Double Cheeseburger", "American": "Half Roast Chicken", "Pizza": "Margherita Pizza",
}

# Honest fallback if the live location call fails — clearly still "near the hotel",
# never claimed to be your history.
_ARRIVAL_FALLBACK = [
    {"restaurant_id": "fb-1", "restaurant_name": "Ippudo", "categories": ["Ramen Restaurant"], "distance_m": 300},
    {"restaurant_id": "fb-2", "restaurant_name": "Tropisueño", "categories": ["Mexican Restaurant"], "distance_m": 420},
    {"restaurant_id": "fb-3", "restaurant_name": "Super Duper Burgers", "categories": ["Burger Joint"], "distance_m": 350},
    {"restaurant_id": "fb-4", "restaurant_name": "The Grove", "categories": ["American Restaurant"], "distance_m": 500},
    {"restaurant_id": "fb-5", "restaurant_name": "Osha Thai", "categories": ["Thai Restaurant"], "distance_m": 520},
]


def _match_cuisine(categories: list[str], pref: list[str] | None = None) -> str | None:
    """Best taste-cuisine this place matches, or None. Highest preference wins.
    `pref` is the traveler's own cuisine order (per persona); defaults to the base."""
    pref = pref or _UBER_EATS_PREF
    blob = " ".join(categories).lower()
    for cuisine in pref:
        if any(alias in blob for alias in _CUISINE_ALIASES.get(cuisine, [])):
            return cuisine
    return None


def _cuisine_of(name: str, categories: list[str], pref: list[str] | None = None) -> str | None:
    """Which of the traveler's taste cuisines this place is, or None. Uses the ChromaDB
    confidence-gated vector classifier when available — it generalises past the
    hand-written aliases (handles French/German/sushi they never covered) and returns
    None on ambiguous places (Korean BBQ, sushi) instead of forcing a weak match. Falls
    back to the regex aliases when Chroma/model is off (tests, plain imports). The
    classifier only fires above a calibrated threshold, so anything it names is at least
    as well-supported as an alias hit — the cuisine_match evaluator stays a valid check."""
    pref = pref or _UBER_EATS_PREF
    if _CHROMA:
        try:
            from arrival_agent.web import chroma_store
            cz, _ = chroma_store.classify_cuisine(name, categories, pref)
            return cz
        except Exception:
            pass
    return _match_cuisine(categories, pref)


def _cuisine_label(categories: list[str]) -> str:
    """A short cuisine label for display — strip Foursquare's 'Restaurant' noise."""
    if not categories:
        return "Restaurant"
    return categories[0].replace(" Restaurant", "").replace(" Place", "").strip() or "Restaurant"


_GEO_MEMO: dict[str, list] = {}   # per-hotel, so the choice set is stable across


def _arrival_find(context):
    """Real restaurants near THIS traveler's hotel, pulled live from the location
    API. Memoized per hotel so the choice set is identical across LangGraph replay
    re-runs (the node re-executes on every resume) — otherwise a resumed pick could
    reference an option a fresh live call didn't return. Falls back to a small
    honest set only if the live call fails."""
    address = (context or {}).get("hotel_address", _HOTEL_ADDRESS)
    if address in _GEO_MEMO:
        return _GEO_MEMO[address]
    try:
        places = restaurants_mod.get_eats_options(address, limit=12)
        result = list(places) if places else _ARRIVAL_FALLBACK
    except Exception:
        result = _ARRIVAL_FALLBACK
    _GEO_MEMO[address] = result
    return result


_NEAR_M = 1500  # keep dinner genuinely close; taste never drags us far from the hotel


def _order_history_dish(tid: str | None, cuisine: str) -> str:
    """The traveler's most-ordered dish in a cuisine — pulled from their Uber Eats
    order history in Chroma when available, else the static synthetic map."""
    if _CHROMA and tid:
        try:
            from arrival_agent.web import chroma_store
            d = chroma_store.top_dish(tid, cuisine)
            if d:
                return d
        except Exception:
            pass
    return _MOST_ORDERED_DISH.get(cuisine, "the house special")


def _arrival_design(candidates, context):
    """Take what's actually open near the hotel (live geo) and rank it by the
    cuisines the traveler orders most on Uber Eats. The match is taste↔location:
    'you order ramen most → this ramen spot near you', never 'your usual here'.

    Proximity gates first — we only taste-rank places that are actually near, so a
    favourite cuisine 1.8 km away never beats a good option two blocks over."""
    pref = context.get("pref") or _UBER_EATS_PREF   # this traveler's cuisine order
    # Classify each candidate's cuisine ONCE (the vector classifier embeds, so we don't
    # want to call it twice per place) and reuse it for both ranking and copy.
    cuis = {id(r): _cuisine_of(r["restaurant_name"], r.get("categories", []), pref)
            for r in candidates}

    def sort_key(r):
        cuisine = cuis[id(r)]
        rank = pref.index(cuisine) if cuisine in pref else 99
        return (rank, r.get("distance_m") or 9999)

    near = [r for r in candidates if (r.get("distance_m") or 9999) <= _NEAR_M]
    if len(near) < 4:  # sparse area — fall back to the nearest handful, still close-first
        near = sorted(candidates, key=lambda r: r.get("distance_m") or 9999)[:6]
    ordered = sorted(near, key=sort_key)
    options = []
    for i, r in enumerate(ordered[:4]):
        name = r["restaurant_name"]
        cuisine = cuis[id(r)]
        label = cuisine or _cuisine_label(r.get("categories", []))
        dist = r.get("distance_m")
        dist_txt = f"{round(dist)} m away" if dist else "near your hotel"
        matched = cuisine is not None

        top_match = i == 0 and matched
        rank = pref.index(cuisine) if cuisine in (pref or []) else 99
        # a "strong" match = a cuisine in the traveler's top third. Only then do we
        # claim a taste match ('a lot') or badge it — otherwise the pick is honest
        # about being a weak fallback (no frequency claim, no badge).
        strong = matched and rank < max(2, len(pref) // 2)
        if matched:
            dish = _order_history_dish(context.get("traveler_id"), cuisine)
            if top_match and rank == 0:
                why = f"you order {cuisine.lower()} most on Uber Eats — {dist_txt}"
            elif strong and top_match:
                why = f"closest to your taste that's open near your hotel — you order {cuisine.lower()} a lot — {dist_txt}"
            elif strong:
                why = f"{cuisine} · a cuisine you order often — {dist_txt}"
            else:  # a cuisine they order, but rarely — no 'a lot' / 'most' claim
                why = f"{cuisine} · the closest open option to your taste — {dist_txt}"
            pitch = (f"Your go-to {cuisine.lower()} order is the {dish} — "
                     f"I can get it from {name} and send it to your room." if strong else
                     f"A {cuisine.lower()} pick near you is the {dish} — I can send it to your room.")
        else:
            dish = "the house special"
            why = f"{label} · {dist_txt}"
            pitch = f"A popular pick at {name} is {dish} — I can send it to your room."

        o = ChoiceOption(
            option_id=f"opt-{i + 1}", restaurant_id=r["restaurant_id"] or f"r{i}",
            restaurant_name=name, items=[dish],
            est_total=float(18 + 2 * i), cuisine_tags=[label],
            why_this_one=why,
        )
        o.est_delivery_at = context.get("deliver_at", _DELIVER)
        o.dish_pitch = pitch
        # Badge only the top card, and only when it's a STRONG (top-third) match.
        if i == 0 and strong:
            o.badge = "matches what you order"
        options.append(o)

    class _CS:
        pass
    cs = _CS()
    cs.options, cs.axis = options, ChoiceAxis.CUISINE
    cs.why_these = "what's open near your hotel now, ranked by what you order most on Uber Eats"
    hotel_short = (context.get("city") or "your hotel").split(",")[0]
    cs.lead = (f"Here's what's open near {hotel_short} right now — ranked by the "
               f"cuisines you order most on Uber Eats:")
    return cs


# Situation feeds per mode (mocked, real-shaped) — these drive the intensity dial.
_SIGNALS = {
    "new":      {"delay_min": 45, "arrival_hour": 1,  "security_wait_min": 45, "pre_flight_min": 120, "security_fresh": True},
    "seasoned": {"delay_min": 45, "arrival_hour": 1,  "security_wait_min": 45, "pre_flight_min": 120, "security_fresh": True},
    "smooth":   {"delay_min": 0,  "arrival_hour": 21, "security_wait_min": 8,  "pre_flight_min": 120, "security_fresh": True},
}

# The selectable travelers — SYNTHETIC seed data. When CONCIERGE_CHROMA=1 this is
# written into ChromaDB once and the app reads travelers back from there at runtime
# (see below); otherwise it's used directly. Each is a full scenario: its own Uber
# Eats taste profile, trip signals that drive the intensity dial, and memory state.
_SEED_TRAVELERS = {
    "priya":  {"name": "Priya Nair",     "tag": "First-time flyer",  "initial": "P", "seasoned": False,
               "taste": ["Thai", "Ramen", "Mexican", "Burger", "American", "Pizza"],
               "city": "Chicago", "hotel": "The Langham, Chicago", "currency": "$",
               "hotel_address": "The Langham, 330 N Wabash Ave, Chicago, IL 60611",
               "flight": "UA 512", "route": "EWR → ORD",
               "bookings": [
                   {"name": "Meet & Greet — airport assist (ORD)", "icon": "🧑‍✈️", "primary": True,
                    "did": "updated your greeter with the new arrival",
                    "confirm": "MG-3307", "at": "greeter meets you at the gate with a nameboard"},
               ],
               "signals": {"delay_min": 45, "arrival_hour": 1,  "security_wait_min": 45, "pre_flight_min": 120, "security_fresh": True}},
    "marcus": {"name": "Marcus Boyd",    "tag": "Road warrior",      "initial": "M", "seasoned": True,
               "taste": ["Burger", "American", "Pizza", "Mexican", "Thai", "Ramen"],
               "city": "New York", "hotel": "The New Yorker, New York", "currency": "$",
               "hotel_address": "The New Yorker Hotel, 481 8th Ave, New York, NY 10001",
               "flight": "DL 208", "route": "SFO → JFK",
               "bookings": [
                   {"name": "Hertz rental car (JFK)", "icon": "🚙", "primary": True,
                    "did": "held the car and told the counter you'll collect later",
                    "confirm": "HZ-88410", "at": "counter holds your car until you arrive"},
               ],
               "signals": {"delay_min": 45, "arrival_hour": 1,  "security_wait_min": 45, "pre_flight_min": 120, "security_fresh": True}},
    "olivia": {"name": "Olivia Chen",    "tag": "On-time optimist",  "initial": "O", "seasoned": False,
               "taste": ["Mexican", "Pizza", "American", "Burger", "Thai", "Ramen"],
               "city": "Los Angeles", "hotel": "The LINE, Los Angeles", "currency": "$",
               "hotel_address": "The LINE Hotel, 3515 Wilshire Blvd, Los Angeles, CA 90010",
               "flight": "AA 118", "route": "JFK → LAX",
               "signals": {"delay_min": 0,  "arrival_hour": 21, "security_wait_min": 8,  "pre_flight_min": 120, "security_fresh": True}},
    "dev":    {"name": "Dev Patel",      "tag": "Red-eye · flight changed", "initial": "D", "seasoned": False,
               "taste": ["Ramen", "Mexican", "Thai", "Burger", "American", "Pizza"],
               "city": "San Francisco", "hotel": "Hotel Zephyr, San Francisco", "currency": "$",
               "hotel_address": "Hotel Zephyr, 250 Beach St, San Francisco, CA 94133",
               "flight": "UA 517", "route": "EWR → SFO",
               # the airline rebooked him onto a different flight — a change, not just a delay
               "flight_change": {"to_flight": "UA 892", "new_arrival": "2:40 AM", "delta": "about 90 min later"},
               "bookings": [
                   {"name": "Uber Reserve — airport pickup", "icon": "🚗", "primary": True, "accent": "uber",
                    "did": "rebooked your pickup for the new landing time",
                    "confirm": "UBR-4C21", "at": "meets you at arrivals ~3:15 AM"},
               ],
               "flag": {"name": "8:00 AM team standup", "note": "you now land at 2:40 AM — that's a rough morning. Want me to ask the organizer to push it?"},
               "signals": {"delay_min": 90, "arrival_hour": 2,  "security_wait_min": 30, "pre_flight_min": 120, "security_fresh": True}},
    "lena":   {"name": "Lena Kowalski",  "tag": "Creature of habit", "initial": "L", "seasoned": False,
               "taste": ["Mexican", "Thai", "Pizza", "American", "Burger", "Ramen"],
               "city": "Berlin", "hotel": "Hotel Zoo, Berlin", "currency": "€",
               "hotel_address": "Hotel Zoo Berlin, Kurfürstendamm 25, 10719 Berlin, Germany",
               "flight": "LH 435", "route": "JFK → BER",
               "bookings": [
                   {"name": "Dinner reservation — Lokal, Mitte", "icon": "🍽️", "primary": True,
                    "did": "released the 9:00 PM table — you'll land too late; I'll sort delivery to your room instead",
                    "confirm": "RES-2291", "at": "table released · switching to Uber Eats delivery"},
               ],
               "signals": {"delay_min": 20, "arrival_hour": 23, "security_wait_min": 35, "pre_flight_min": 120, "security_fresh": True}},
}

# Load travelers from ChromaDB when CONCIERGE_CHROMA=1 (the web server sets it):
# seed the synthetic data above into Chroma once, then read it back — so the app
# runs off the data store, not the literal. Tests / plain imports fall back to the
# seed, so nothing depends on a running container. `_CHROMA` records which path won.
_CHROMA = False
_PERSONAS = _SEED_TRAVELERS
if os.environ.get("CONCIERGE_CHROMA") == "1":
    try:
        from arrival_agent.web import chroma_store
        if chroma_store.available():
            chroma_store.seed(_SEED_TRAVELERS)   # wipe+reseed so edits always propagate
            loaded = chroma_store.load_travelers()
            if loaded:
                _PERSONAS = loaded
                _CHROMA = True
    except Exception:
        pass

# Location defaults for the non-persona demo modes (new/seasoned/smooth) and any
# fallback — San Francisco, matching the original single-city demo.
_SF_LOC = {"city": "San Francisco", "hotel": _HOTEL, "hotel_address": _HOTEL_ADDRESS,
           "flight": "UA 517", "route": "EWR → SFO", "currency": "$"}


def _loc(mode: str) -> dict:
    """The traveler's location + trip facts (hotel, city, flight, currency)."""
    p = _PERSONAS.get(mode)
    if not p:
        return _SF_LOC
    return {k: p[k] for k in ("city", "hotel", "hotel_address", "flight", "route", "currency")}


def _trip_extras(mode: str):
    """Other arrival-coupled bookings the agent syncs on a disruption (Uber ride,
    porter, rental car…), plus one it flags rather than moves on its own."""
    p = _PERSONAS.get(mode, {})
    return p.get("bookings", []), p.get("flag")


def _uber_ride(mode: str):
    """The traveler's booked Uber ride, if any — used to hand off to live tracking
    once they land."""
    bookings, _ = _trip_extras(mode)
    return next((b for b in bookings
                 if b.get("accent") == "uber" or "Uber" in b.get("name", "")), None)


def _rental_car(mode: str):
    """A rental-car booking, if any. If the traveler is driving themselves, the
    agent must NOT also book an Uber — one way to the hotel, not two."""
    bookings, _ = _trip_extras(mode)
    return next((b for b in bookings if "rental" in b.get("name", "").lower()), None)


# Scheduled arrival (local, 24h) per mode. The ACTUAL arrival is this + the
# delay (or the flight-change time), computed once and used everywhere — so the
# header, the read chip, the gate line and the hotel note never disagree.
_SCHED = {
    "priya": "00:30", "marcus": "00:30", "olivia": "21:40", "lena": "22:55",
    "new": "00:30", "seasoned": "00:30", "smooth": "21:40",
}


def _raw_signals(mode: str) -> dict:
    if mode in _PERSONAS:
        return _PERSONAS[mode]["signals"]
    return _SIGNALS.get(mode, _SIGNALS["new"])


def _arrival_dt(mode: str) -> datetime:
    """The actual arrival time: scheduled + delay, or the flight-change time."""
    fc = _PERSONAS.get(mode, {}).get("flight_change")
    if fc:
        return datetime.strptime(fc["new_arrival"].strip().upper(), "%I:%M %p")
    base = datetime.strptime(_SCHED.get(mode, "00:30"), "%H:%M")
    return base + timedelta(minutes=_raw_signals(mode).get("delay_min", 0))


def _arrival_str(mode: str) -> str:
    """Display form, e.g. '1:15 AM'."""
    return _arrival_dt(mode).strftime("%I:%M %p").lstrip("0")


def _signals_for(mode: str) -> dict:
    # a copy with the computed arrival stamped in, so read()/assess and the UI agree
    s = dict(_raw_signals(mode))
    dt = _arrival_dt(mode)
    s["arrival_hour"] = dt.hour
    s["arrival_hhmm"] = _arrival_str(mode)
    return s


def _taste_for(mode: str) -> list[str]:
    # When Chroma is on, the taste ranking is DERIVED from the traveler's Uber Eats
    # order history in the DB (most-ordered cuisine first) — not the static list.
    if _CHROMA and mode in _PERSONAS:
        try:
            from arrival_agent.web import chroma_store
            ranked = chroma_store.taste_for(mode)
            if ranked:
                return ranked
        except Exception:
            pass
    if mode in _PERSONAS:
        return _PERSONAS[mode].get("taste") or _UBER_EATS_PREF
    return _UBER_EATS_PREF


def _is_seasoned(mode: str) -> bool:
    if mode in _PERSONAS:
        return _PERSONAS[mode]["seasoned"]
    return mode == "seasoned"


def personas() -> list[dict]:
    """The traveler roster for the login screen."""
    return [{"id": k, "name": v["name"], "tag": v["tag"], "initial": v["initial"], "city": v["city"]}
            for k, v in _PERSONAS.items()]

_DEP_INTRO_HIGH = "Before you head out — security's running long right now. Leave sooner:"
_DEP_INTRO_LOW = "Before you head out — one thing worth doing:"


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
    sig = _signals_for(mode)
    loc = _loc(mode)
    fc = _PERSONAS.get(mode, {}).get("flight_change")
    city = loc["city"]
    delay = sig.get("delay_min", 0)
    arr = _arrival_str(mode)   # single source of truth: scheduled + delay / change
    welcome = f"Welcome to {city} 👋"
    # international arrivals clear immigration + customs, so the exit runs much longer
    intl = _is_international(loc.get("route", ""))
    exit_min = INTL_EXIT_MIN if intl else AIRPORT_EXIT_MIN
    room_dt = _arrival_dt(mode) + timedelta(minutes=exit_min + RIDE_TO_HOTEL_MIN)
    room_str = room_dt.strftime("%I:%M %p").lstrip("0")
    if intl:
        exit_line = (f"You're about {exit_min} min from being out of the airport — deplane, "
                     f"then the immigration line (international arrivals run long), baggage, "
                     f"and customs. Figure in your room by ~{room_str}.")
    else:
        exit_line = (f"You're about {exit_min} min from being out of the airport "
                     f"(deplane, then bags) — in your room by ~{room_str}.")
    if fc:  # the airline rebooked him — announce the change, then take care of the hotel
        gate_intro = [
            f"✈️ Flight change — the airline moved you off {loc['flight']} onto {fc['to_flight']}.",
            f"You'll now land around {arr} ({fc['delta']}). Let me take care of the hotel so "
            f"your room's held for the new time.",
        ]
    else:
        gate_intro = (f"Hours later, at the gate — your flight slipped {delay} min, so you'll "
                      f"land around {arr}. I'll give the hotel a heads-up so your room's held.")
    smooth_arrival = [welcome,
                      "You're in early tonight — everything's on track, kitchens are open and "
                      "the line was clear. I'll let the hotel know your ETA so check-in's ready:"]
    segs = []

    dep = _departure_segment(sig, memory)
    if dep:
        segs.append(dep)

    if assess(Moment.ARRIVAL, sig) == Intensity.HIGH:
        # at the gate: hold the room (a seasoned traveler handles it themselves,
        # so memory drops it and this segment is skipped)
        hotel = _hotel_list(memory)
        if hotel:
            segs.append((gate_intro, ActionList(
                moment=Moment.DELAY, reasoning="hold the room", items=hotel,
                intensity="high", read=read(Moment.DELAY, sig))))
        # on arrival: welcome + airport-exit time + cuisine-ranked dinner
        segs.append(([welcome, exit_line], ActionList(
            moment=Moment.ARRIVAL, reasoning="dinner near the hotel",
            items=[curate_actions(Moment.ARRIVAL).items[0]], intensity="high", read="")))
    else:
        # calm on-time arrival: welcome, the agent quietly gives the hotel your ETA
        # (action-first), then a dinner offer since kitchens are open at this hour.
        segs.append((smooth_arrival, ActionList(
            moment=Moment.DELAY, reasoning="all good", items=_hotel_list(memory),
            intensity="low", read="")))
        segs.append(([f"You're in around {arr} — plenty of time for dinner if you want it."],
                     ActionList(moment=Moment.ARRIVAL, reasoning="dinner near the hotel",
                                items=[curate_actions(Moment.ARRIVAL).items[0]],
                                intensity="low", read="")))
    return segs


def _handlers(mode: str = "new"):
    hotel = _loc(mode)["hotel"]
    return {
        ActionKind.HEADS_UP: HeadsUpHandler(),
        ActionKind.NOTIFY_HOTEL: NotifyHotelHandler(
            send=lambda note: send_hotel_note(hotel, note),
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
    sig = _signals_for(mode)
    loc = _loc(mode)
    fc = _PERSONAS.get(mode, {}).get("flight_change")
    delay = sig.get("delay_min", 0)
    arr = _arrival_str(mode)
    if fc:
        arrival = f"~{arr} (flight changed)"
    elif not delay:
        arrival = f"~{arr} (on time)"
    else:
        arrival = f"~{arr} (delayed {delay}m)"
    meta = _PERSONAS.get(mode)
    return {
        "flight": loc["flight"], "route": loc["route"], "hotel": loc["hotel"],
        "arrival": arrival, "currency": loc["currency"], "city": loc["city"],
        "changed": bool(fc), "new_flight": fc["to_flight"] if fc else None,
        "traveler": meta["name"] if meta else None,
        "initial": meta["initial"] if meta else "A",
        "security_min": sig.get("security_wait_min"),
        "delay_min": sig.get("delay_min", 0),
        "source": "from your booking email",
    }


def _context(mode: str = "new") -> dict:
    sig = _signals_for(mode)
    loc = _loc(mode)
    fc = _PERSONAS.get(mode, {}).get("flight_change")
    delay = sig.get("delay_min", 0)
    arrival_hhmm = _arrival_str(mode)
    ctx = {"arrival_hhmm": arrival_hhmm, "city": loc["hotel"], "deliver_at": _DELIVER,
           "hotel_address": loc["hotel_address"],   # where the geo tool searches
           "traveler_id": mode,                     # for Chroma order-history lookups
           "currency": loc["currency"], "city_name": loc["city"],
           "time_of_day": f"{_ARRIVAL:%H:%M} (room arrival estimate)",
           "fatigue": "high late-night arrival after a flight",
           "pref": _taste_for(mode)}   # this traveler's Uber Eats cuisine order
    # what the hotel note is ABOUT — drives the wording (changed / delayed / on-time)
    ctx["notify_kind"] = "changed" if fc else ("delayed" if delay else "ontime")
    if fc:
        ctx["new_flight"] = fc["to_flight"]
    # Action-first, always: the agent notifies the hotel itself and reports back —
    # no approval tap, whether the trip is delayed, changed, or on time.
    ctx["auto_notify"] = True
    return ctx


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
    if kind == "ask_hotel":
        if any(w in t for w in ("yes", "notify", "tell", "let them", "go ahead", "sure", "ok", "please", "do it")):
            return {"decision": "yes", "text": text}
        return {"decision": "no", "text": text}
    if kind == "book_ride":
        if any(w in t for w in ("book", "yes", "ride", "uber", "go ahead", "sure", "ok", "please", "do it")):
            return {"decision": "book", "text": text}
        return {"decision": "decline", "text": text}
    if kind == "confirm_dish":
        if any(w in t for w in ("order", "yes", "confirm", "send", "get it", "go ahead", "sure", "please")):
            return {"decision": "confirm", "text": text}
        return {"decision": "back", "text": text}
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
    current: dict | None = None  # the pause payload the user is answering (for say())
    seq: int = 0                 # event counter — persisted, so reconnect can replay
    resume: bool = False         # reattached after a restart; replay log then continue


class ConciergeRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, ConciergeRun] = {}

    def create(self, mode: str = "new") -> ConciergeRun:
        if mode not in _SIGNALS and mode not in _PERSONAS:
            mode = "new"
        memory = seed_seasoned() if _is_seasoned(mode) else None
        run = ConciergeRun(
            run_id=uuid4().hex[:12], segments=_segments(memory, mode), mode=mode
        )
        self._runs[run.run_id] = run
        store.record_run(run.run_id, mode)   # so a restarted server can rebuild it
        return run

    def reattach(self, run_id: str) -> ConciergeRun | None:
        """Rebuild a run the in-memory registry lost (server restarted). Returns a
        resume-mode run whose driver replays the event log, then continues from the
        paused moment persisted in the LangGraph checkpoint. None if unknown.

        OFF by default: replaying a persisted run means an old EventSource that
        reconnects after a restart would show STALE data. Set ARRIVAL_AGENT_DURABLE=1
        to enable cross-restart resume (the frontend otherwise just starts fresh)."""
        if os.environ.get("ARRIVAL_AGENT_DURABLE") != "1":
            return None
        mode = store.mode_of(run_id)
        if mode is None:
            return None
        memory = seed_seasoned() if _is_seasoned(mode) else None
        run = ConciergeRun(
            run_id=run_id, segments=_segments(memory, mode), mode=mode, resume=True
        )
        self._runs[run_id] = run
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
        kind = run.current["kind"] if isinstance(run.current, dict) else run.current.kind
        return self.submit(run_id, parse_intent(text, kind))

    def discard(self, run_id: str) -> None:
        self._runs.pop(run_id, None)


registry = ConciergeRegistry()


def _pause_payload(step: Pause) -> dict:
    return {"action_id": step.action_id, "kind": step.kind, "title": step.title, "payload": step.payload}


def _acted_payload(v: dict) -> dict:
    """What the agent did on its own — shown to the traveler after the fact."""
    when = v.get("when") or "later tonight"
    kind = v.get("kind")
    if kind == "changed":
        text = (f"✅ Done — I've updated the hotel about your flight change"
                f"{' (now ' + v['new_flight'] + ')' if v.get('new_flight') else ''}. "
                f"They'll hold your room for your new arrival, ~{when}.")
    elif kind == "ontime":
        text = (f"✅ Done — I gave the hotel your ETA (~{when}) so check-in's "
                f"quick when you get there.")
    else:
        text = (f"✅ Done — I've let the hotel know you'll arrive around ~{when}, "
                f"so they'll hold your room.")
    return {"text": text, "note": v.get("note")}


async def _emit(run: ConciergeRun, kind: str, payload: dict) -> None:
    """Stream an event to the browser AND persist it, so a reconnect after a
    server restart can replay the exact thread."""
    run.seq += 1
    store.append(run.run_id, run.seq, kind, payload)
    await run.queue.put((kind, payload))


def _is_complete(snap) -> bool:
    return bool(snap.created_at) and not snap.next and "outcomes" in (snap.values or {})


def _pending_pause(snap) -> dict | None:
    for t in (snap.tasks or ()):
        for it in (getattr(t, "interrupts", None) or ()):
            return it.value
    return None


async def drive(run: ConciergeRun) -> None:
    """Walk the trip's moments in order, driving each through the LangGraph graph.
    On `run.resume` (reattached after a server restart), first replay the persisted
    event log to rebuild the browser thread, then continue from the moment still
    paused in the checkpoint — skipping already-finished moments."""
    loop = asyncio.get_running_loop()
    if run.queue is None:
        run.queue = asyncio.Queue()
    from arrival_agent.web import concierge_graph as cg   # lazy: avoids import cycle

    outcomes: list[dict] = []
    synced = False
    announced = False        # has the disruption (delay/change) been surfaced yet?
    catching_up = run.resume  # still replaying / skipping finished moments?

    try:
        if run.resume:   # rebuild the thread the browser lost, straight from the log
            replayed = store.events_of(run.run_id)
            for kind, payload in replayed:
                await run.queue.put((kind, payload))
            run.seq = len(replayed)
        else:
            await _emit(run, "context", _trip_context(run.mode))

        for seg_index, (intro, actions) in enumerate(run.segments):
            if actions.moment == Moment.DELAY:   # the gate/change announcement lives here
                announced = True

            config = {"configurable": {"thread_id": f"{run.run_id}:{seg_index}"}}
            pending: dict | None = None
            skip_pre = False
            if catching_up:
                snap = cg.graph.get_state(config)
                if _is_complete(snap):          # finished before the restart — skip it
                    outcomes.extend(snap.values.get("outcomes", []))
                    continue
                catching_up = False             # this is the moment to resume/continue from
                pending = _pending_pause(snap)
                skip_pre = pending is not None  # its pre-events were already replayed

            # --- pre-emission (skipped when resuming an already-shown pause) ---
            if not skip_pre:
                # before the arrival welcome, sync the rest of the trip's bookings —
                # each traveler has a different one (meet-&-greet / rental / Uber /
                # dinner reservation). Fires once, only on a disruption.
                if not synced and actions.moment == Moment.ARRIVAL:
                    bookings, flag = _trip_extras(run.mode)
                    if bookings:
                        synced = True
                        if announced:
                            lead = ("I also took care of the other bookings on this trip that "
                                    "move with your arrival:")
                        else:
                            # nothing surfaced the disruption yet (a seasoned traveler whose
                            # hotel beat was memory-trimmed) — lead with it here.
                            fc = _PERSONAS.get(run.mode, {}).get("flight_change")
                            delay = _signals_for(run.mode).get("delay_min", 0)
                            if fc:
                                lead = ("Your flight was changed — I re-synced the bookings tied "
                                        "to your new arrival:")
                            else:
                                lead = (f"Heads-up: your flight's running about {delay} min late. "
                                        f"I re-synced the bookings tied to your new arrival:")
                        await _emit(run, "agent", {"text": lead})
                        primary = [b for b in bookings if b.get("primary") or b.get("at")]
                        rest = [b for b in bookings if b not in primary]
                        for b in primary:               # its own confirmed-booking card
                            await _emit(run, "confirm", b)
                        if rest or flag:
                            await _emit(run, "synced", {"items": rest, "flag": flag})
                if getattr(actions, "read", ""):   # show the signals -> verdict (data flow)
                    await _emit(run, "read", {"text": actions.read, "intensity": actions.intensity})
                for line in (intro if isinstance(intro, list) else [intro]):
                    await _emit(run, "agent", {"text": line})
                # arrival ride: land -> exit -> ONE way to the hotel -> dinner.
                # Exactly one transport: a pre-booked Uber (track it), a rental car
                # (they drive — no Uber), or book a fresh Uber.
                if actions.moment == Moment.ARRIVAL:
                    ride = _uber_ride(run.mode)
                    rental = _rental_car(run.mode)
                    hotel = _loc(run.mode)["hotel"].split(",")[0]
                    if ride:
                        # a pickup was already re-booked at the gate — hand off to tracking
                        await _emit(run, "track", {
                            "confirm": ride.get("confirm"), "at": ride.get("at"),
                            "url": "https://m.uber.com/",
                        })
                    elif rental:
                        # driving himself — the rental car IS the ride; no Uber
                        await _emit(run, "agent", {"text":
                            f"Your rental car's ready at the counter ({rental.get('confirm','held')}) — "
                            f"grab it and you're a short drive to {hotel}. No ride to book."})
                    else:
                        # everyone else books their ride to the hotel now, one tap
                        pause = {"action_id": "book-ride", "kind": "book_ride",
                                 "title": "Ride to your hotel", "payload": {"hotel": hotel}}
                        await _emit(run, "todo", pause)
                        run.response = loop.create_future()
                        run.awaiting = True
                        run.current = pause
                        ui = await run.response
                        run.awaiting = False
                        run.current = None
                        await _emit(run, "you", {"action_id": "book-ride",
                                                 "decision": ui.get("decision"), "text": ui.get("text")})
                        if ui.get("decision") in ("book", "yes", "confirm"):
                            conf = "UBR-" + run.run_id[:4].upper()
                            await _emit(run, "confirm", {
                                "name": f"Uber to {hotel}", "icon": "🚗", "accent": "uber",
                                "did": "booked your ride from the airport",
                                "confirm": conf, "at": f"meets you at arrivals in ~{AIRPORT_EXIT_MIN} min"})
                            await _emit(run, "track", {"confirm": conf,
                                                       "at": "meets you at arrivals", "url": "https://m.uber.com/"})

            # --- drive this moment through the LangGraph StateGraph + SQLite ---
            if pending is not None:
                # the todo was already replayed; re-arm the await and resume the graph
                run.response = loop.create_future()
                run.awaiting = True
                run.current = pending
                user_input = await run.response
                run.awaiting = False
                run.current = None
                await _emit(run, "you", {
                    "action_id": pending["action_id"],
                    "decision": user_input.get("decision"),
                    "text": user_input.get("text"),
                })
                result = await asyncio.to_thread(
                    cg.graph.invoke, cg.Command(resume=user_input), config)
            else:
                result = await asyncio.to_thread(
                    cg.graph.invoke, {"mode": run.mode, "seg": seg_index}, config)

            while result.get("__interrupt__"):
                intr = result["__interrupt__"]
                pause = intr[0].value if isinstance(intr, (list, tuple)) else intr.value
                await _emit(run, "todo", pause)
                run.response = loop.create_future()
                run.awaiting = True
                run.current = pause
                user_input = await run.response
                run.awaiting = False
                run.current = None
                await _emit(run, "you", {
                    "action_id": pause["action_id"],
                    "decision": user_input.get("decision"),
                    "text": user_input.get("text"),
                })
                result = await asyncio.to_thread(
                    cg.graph.invoke, cg.Command(resume=user_input), config)

            seg_outcomes = result.get("outcomes", [])
            for oc in seg_outcomes:   # the agent auto-acted (no approval) — report back
                v = oc.get("outcome")
                if isinstance(v, dict) and v.get("auto") and v.get("sent"):
                    await _emit(run, "acted", _acted_payload(v))
            outcomes.extend(seg_outcomes)  # moment finished
        await _emit(run, "done", {"outcomes": outcomes})
    except Exception as e:  # never hang the stream
        await run.queue.put(("error", {"message": f"{type(e).__name__}: {e}"}))
    finally:
        await run.queue.put((_CLOSE, None))
        registry.discard(run.run_id)
