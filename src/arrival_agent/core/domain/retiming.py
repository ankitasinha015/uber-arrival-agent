"""Domain: the re-timing math — the heart of the agent.

The agent's hardest decision is knowing when NOT to act. Acting too early =
food at the front desk while the rider is still in customs. Acting too late =
no restaurant prep time left. This module computes:

  1. estimate_room_arrival(...)  -> when the rider reaches the hotel room +
                                    how confident we are
  2. place_order_by(...)         -> latest moment to place the order and
                                    still hit the delivery target
  3. decide_timing(...)          -> the wait-vs-act decision plus reasoning

The estimate tightens monotonically as stronger signals arrive:

    trip_booked  → scheduled arrival + 90 min slack    (loose)
    flight delayed → estimated arrival + 50 min slack
    flight on_ground → actual arrival + 35 min slack
    ride_started → now + live ETA + 12 min check-in    (tight, ±8 min)
    ride_ended → now + 12 min                          (tighter, ±5 min)
    check_in → now                                     (anchor, ±2 min)

`decide_timing` is the only place the wait-vs-act rule lives. Adapters call
it; the rule is identical across LangGraph, raw, and naive (with the naive
adapter wired to ignore the wait recommendation — that's exactly the contrast
the framework comparison shows).

This module is pure: no I/O, no LLM calls, no tool calls. Domain logic only.
The adapter is responsible for calling the eta tool when ride_started arrives
and passing the result in via `current_ride_eta_min`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from arrival_agent.core.events import EventType, TripEvent


# --- timing assumptions (named constants, override via decide_timing kwargs) --

# Ground-side time between events. These are the *expected* additional minutes
# from a given event to the rider reaching the hotel room.
DEPLANE_AND_BAGS_MIN = 23   # gate -> curb
DEFAULT_RIDE_MIN = 30       # fallback when ride hasn't started and no ETA known
CHECK_IN_QUEUE_MIN = 12     # arrive at hotel -> in room

# Half-width of the confidence window at each event grade (minutes).
# Smaller = more confident. These are the thresholds the wait-vs-act rule
# compares against `cold_food_tolerance`.
UNCERTAINTY_TRIP_BOOKED = 90.0
UNCERTAINTY_FLIGHT_DELAYED = 50.0
UNCERTAINTY_FLIGHT_ON_GROUND = 35.0
UNCERTAINTY_RIDE_STARTED = 8.0
UNCERTAINTY_RIDE_ENDED = 5.0
UNCERTAINTY_CHECK_IN = 2.0

# Defaults for the order timing math.
DEFAULT_PREP_MIN = 15
DEFAULT_COURIER_MIN = 12
DEFAULT_DELIVERY_AFTER_ARRIVAL_MIN = 20
DEFAULT_COLD_FOOD_TOLERANCE_MIN = 10.0
DEFAULT_SAFETY_MARGIN_MIN = 3.0


# --- return types -------------------------------------------------------------


@dataclass
class ArrivalEstimate:
    """Best current estimate of when the rider reaches their hotel room."""

    estimated_at: datetime
    uncertainty_minutes: float      # half-width of the confidence window
    grade: str                       # the event grade behind this estimate
    derived_from: EventType | None   # the strongest event used


@dataclass
class TimingDecision:
    """Output of the wait-vs-act rule. Adapters surface `reason` to the user."""

    action: str                      # "wait" or "act"
    reason: str
    estimate: ArrivalEstimate
    place_by: datetime               # latest moment the order can be placed


# --- helpers ------------------------------------------------------------------


def _latest(events: list[TripEvent], event_type: EventType) -> TripEvent | None:
    """The latest event of `event_type` in `events` (by timestamp)."""
    matching = [e for e in events if e.type == event_type]
    return max(matching, key=lambda e: e.at) if matching else None


# --- core math ----------------------------------------------------------------


def estimate_room_arrival(
    events: list[TripEvent],
    *,
    scheduled_flight_arrival: datetime | None = None,
    current_ride_eta_min: int | None = None,
) -> ArrivalEstimate:
    """Best current estimate of room arrival given the events seen so far.

    `scheduled_flight_arrival` comes from the scenario itinerary; required
    when only `trip_booked` has been seen.

    `current_ride_eta_min` is the live Mapbox ETA the adapter fetched when
    the ride started; optional. When absent and a ride is in flight, falls
    back to `DEFAULT_RIDE_MIN`.

    Walks down from strongest signal to weakest and uses the first match.
    """
    # 1. check_in — rider is in the room (or about to be).
    check_in = _latest(events, EventType.CHECK_IN)
    if check_in is not None:
        return ArrivalEstimate(
            estimated_at=check_in.at,
            uncertainty_minutes=UNCERTAINTY_CHECK_IN,
            grade="check_in",
            derived_from=EventType.CHECK_IN,
        )

    # 2. ride_ended — rider at the hotel, just check-in queue left.
    ride_ended = _latest(events, EventType.RIDE_ENDED)
    if ride_ended is not None:
        return ArrivalEstimate(
            estimated_at=ride_ended.at + timedelta(minutes=CHECK_IN_QUEUE_MIN),
            uncertainty_minutes=UNCERTAINTY_RIDE_ENDED,
            grade="ride_ended",
            derived_from=EventType.RIDE_ENDED,
        )

    # 3. ride_started — live ETA available.
    ride_started = _latest(events, EventType.RIDE_STARTED)
    if ride_started is not None:
        ride_min = current_ride_eta_min if current_ride_eta_min is not None else DEFAULT_RIDE_MIN
        return ArrivalEstimate(
            estimated_at=ride_started.at + timedelta(minutes=ride_min + CHECK_IN_QUEUE_MIN),
            uncertainty_minutes=UNCERTAINTY_RIDE_STARTED,
            grade="ride_started",
            derived_from=EventType.RIDE_STARTED,
        )

    # 4. flight_status — on_ground (tighter) or delayed (looser).
    flight = _latest(events, EventType.FLIGHT_STATUS)
    if flight is not None:
        payload = flight.parsed()
        status = getattr(payload, "status", None)
        if status == "on_ground":
            anchor = getattr(payload, "actual_arrival", None) or flight.at
            return ArrivalEstimate(
                estimated_at=anchor + timedelta(
                    minutes=DEPLANE_AND_BAGS_MIN + DEFAULT_RIDE_MIN + CHECK_IN_QUEUE_MIN
                ),
                uncertainty_minutes=UNCERTAINTY_FLIGHT_ON_GROUND,
                grade="flight_on_ground",
                derived_from=EventType.FLIGHT_STATUS,
            )
        anchor = getattr(payload, "estimated_arrival", None) or flight.at
        return ArrivalEstimate(
            estimated_at=anchor + timedelta(
                minutes=DEPLANE_AND_BAGS_MIN + DEFAULT_RIDE_MIN + CHECK_IN_QUEUE_MIN
            ),
            uncertainty_minutes=UNCERTAINTY_FLIGHT_DELAYED,
            grade="flight_delayed",
            derived_from=EventType.FLIGHT_STATUS,
        )

    # 5. trip_booked only — use the scheduled flight arrival from itinerary.
    if scheduled_flight_arrival is None:
        raise ValueError(
            "no usable events and no scheduled_flight_arrival — cannot estimate"
        )
    return ArrivalEstimate(
        estimated_at=scheduled_flight_arrival + timedelta(
            minutes=DEPLANE_AND_BAGS_MIN + DEFAULT_RIDE_MIN + CHECK_IN_QUEUE_MIN
        ),
        uncertainty_minutes=UNCERTAINTY_TRIP_BOOKED,
        grade="trip_booked",
        derived_from=EventType.TRIP_BOOKED,
    )


def place_order_by(
    room_arrival: datetime,
    *,
    prep_minutes: int = DEFAULT_PREP_MIN,
    courier_minutes: int = DEFAULT_COURIER_MIN,
    deliver_after_arrival_min: int = DEFAULT_DELIVERY_AFTER_ARRIVAL_MIN,
) -> datetime:
    """Latest moment to place an order and still have food arrive
    ~`deliver_after_arrival_min` after `room_arrival`.

        target_delivery = room_arrival + deliver_after_arrival
        place_by        = target_delivery − prep − courier
    """
    target_delivery = room_arrival + timedelta(minutes=deliver_after_arrival_min)
    return target_delivery - timedelta(minutes=prep_minutes + courier_minutes)


# --- the wait-vs-act rule -----------------------------------------------------


def decide_timing(
    events: list[TripEvent],
    *,
    now: datetime,
    scheduled_flight_arrival: datetime | None = None,
    current_ride_eta_min: int | None = None,
    cold_food_tolerance_min: float = DEFAULT_COLD_FOOD_TOLERANCE_MIN,
    safety_margin_min: float = DEFAULT_SAFETY_MARGIN_MIN,
    prep_minutes: int = DEFAULT_PREP_MIN,
    courier_minutes: int = DEFAULT_COURIER_MIN,
    deliver_after_arrival_min: int = DEFAULT_DELIVERY_AFTER_ARRIVAL_MIN,
) -> TimingDecision:
    """Decide whether to wait or act, with a one-line reason.

    Rule:
        ACT when:
          uncertainty(room_arrival) <= cold_food_tolerance
          AND  now >= place_by - safety_margin
        else WAIT.

    Knowing when NOT to act is the agent's hardest capability. Until the
    estimate is tight enough (typically ride_started), every minute of slack
    in the room-arrival prediction translates 1:1 into the food sitting cold
    at the front desk. Acting on a loose estimate IS the failure mode.
    """
    estimate = estimate_room_arrival(
        events,
        scheduled_flight_arrival=scheduled_flight_arrival,
        current_ride_eta_min=current_ride_eta_min,
    )
    place_by = place_order_by(
        estimate.estimated_at,
        prep_minutes=prep_minutes,
        courier_minutes=courier_minutes,
        deliver_after_arrival_min=deliver_after_arrival_min,
    )

    if estimate.uncertainty_minutes > cold_food_tolerance_min:
        return TimingDecision(
            action="wait",
            reason=(
                f"estimate is ±{estimate.uncertainty_minutes:.0f} min "
                f"(from {estimate.grade}); acting now risks food arriving "
                f"while the rider is still in transit"
            ),
            estimate=estimate,
            place_by=place_by,
        )

    if now < place_by - timedelta(minutes=safety_margin_min):
        wait_minutes = (place_by - timedelta(minutes=safety_margin_min) - now).total_seconds() / 60
        return TimingDecision(
            action="wait",
            reason=(
                f"estimate is tight (±{estimate.uncertainty_minutes:.0f} min) "
                f"but still {wait_minutes:.0f} min before place-by deadline"
            ),
            estimate=estimate,
            place_by=place_by,
        )

    return TimingDecision(
        action="act",
        reason=(
            f"estimate tight (±{estimate.uncertainty_minutes:.0f} min from "
            f"{estimate.grade}), within safety window of place-by {place_by.isoformat()}"
        ),
        estimate=estimate,
        place_by=place_by,
    )
