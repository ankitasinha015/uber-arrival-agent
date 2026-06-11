"""Tests for the re-timing math — the agent's hardest decisions.

Goal: prove (1) the estimate tightens monotonically as stronger signals arrive,
(2) place_order_by works backwards correctly, and (3) decide_timing applies the
wait-vs-act rule the way the design says it should.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from arrival_agent.core.domain import retiming
from arrival_agent.core.domain.retiming import (
    DEFAULT_COURIER_MIN,
    DEFAULT_PREP_MIN,
    UNCERTAINTY_CHECK_IN,
    UNCERTAINTY_FLIGHT_DELAYED,
    UNCERTAINTY_FLIGHT_ON_GROUND,
    UNCERTAINTY_RIDE_ENDED,
    UNCERTAINTY_RIDE_STARTED,
    UNCERTAINTY_TRIP_BOOKED,
    decide_timing,
    estimate_room_arrival,
    place_order_by,
)
from arrival_agent.core.events import EventType, TripEvent


PDT = timezone(timedelta(hours=-7))


def _t(h: int, m: int = 0) -> datetime:
    """Helper: build a datetime on 2026-05-20 at h:m PDT."""
    return datetime(2026, 5, 20, h, m, tzinfo=PDT)


def _e(kind: str, when: datetime, **payload) -> TripEvent:
    return TripEvent(type=kind, at=when, payload=payload)


SCHEDULED = _t(22, 55)  # itinerary's flight arrival


# --- estimate_room_arrival ----------------------------------------------------


def test_estimate_uses_scheduled_arrival_when_only_trip_booked():
    est = estimate_room_arrival(
        [_e("trip_booked", _t(15))],
        scheduled_flight_arrival=SCHEDULED,
    )
    assert est.uncertainty_minutes == UNCERTAINTY_TRIP_BOOKED
    assert est.grade == "trip_booked"
    # ~ scheduled + 23 + 30 + 12 = +65 min
    assert est.estimated_at == SCHEDULED + timedelta(minutes=23 + 30 + 12)


def test_estimate_tightens_with_flight_delayed():
    revised_arrival = _t(23, 40)
    est = estimate_room_arrival(
        [
            _e("trip_booked", _t(15)),
            _e("flight_status", _t(21, 30),
               status="delayed", estimated_arrival=revised_arrival.isoformat()),
        ],
        scheduled_flight_arrival=SCHEDULED,
    )
    assert est.uncertainty_minutes == UNCERTAINTY_FLIGHT_DELAYED
    assert est.uncertainty_minutes < UNCERTAINTY_TRIP_BOOKED  # tightens
    assert est.grade == "flight_delayed"
    assert est.estimated_at == revised_arrival + timedelta(minutes=23 + 30 + 12)


def test_estimate_tightens_with_on_ground():
    on_ground_at = _t(23, 35)
    est = estimate_room_arrival(
        [
            _e("trip_booked", _t(15)),
            _e("flight_status", _t(23, 35),
               status="on_ground", actual_arrival=on_ground_at.isoformat()),
        ],
        scheduled_flight_arrival=SCHEDULED,
    )
    assert est.uncertainty_minutes == UNCERTAINTY_FLIGHT_ON_GROUND
    assert est.uncertainty_minutes < UNCERTAINTY_FLIGHT_DELAYED
    assert est.estimated_at == on_ground_at + timedelta(minutes=23 + 30 + 12)


def test_estimate_uses_live_eta_when_ride_started():
    ride_at = _t(0, 5).replace(day=21)  # next day
    est = estimate_room_arrival(
        [_e("ride_started", ride_at)],
        current_ride_eta_min=16,  # live Mapbox ETA
    )
    assert est.uncertainty_minutes == UNCERTAINTY_RIDE_STARTED
    assert est.grade == "ride_started"
    # ride_at + 16 (ETA) + 12 (check-in queue)
    assert est.estimated_at == ride_at + timedelta(minutes=16 + 12)


def test_estimate_falls_back_to_default_ride_when_no_eta():
    ride_at = _t(0, 5).replace(day=21)
    est = estimate_room_arrival([_e("ride_started", ride_at)])
    assert est.estimated_at == ride_at + timedelta(minutes=30 + 12)  # DEFAULT_RIDE_MIN+queue


def test_estimate_tightens_at_ride_ended():
    end_at = _t(0, 40).replace(day=21)
    est = estimate_room_arrival([_e("ride_ended", end_at)])
    assert est.uncertainty_minutes == UNCERTAINTY_RIDE_ENDED
    assert est.estimated_at == end_at + timedelta(minutes=12)


def test_estimate_anchors_at_check_in():
    in_at = _t(0, 52).replace(day=21)
    est = estimate_room_arrival([_e("check_in", in_at)])
    assert est.uncertainty_minutes == UNCERTAINTY_CHECK_IN
    assert est.estimated_at == in_at


def test_estimate_uses_strongest_signal_when_multiple_events_present():
    """Stronger signals should win, even if earlier events exist."""
    est = estimate_room_arrival(
        [
            _e("trip_booked", _t(15)),
            _e("flight_status", _t(21, 30), status="delayed",
               estimated_arrival=_t(23, 40).isoformat()),
            _e("ride_started", _t(0, 5).replace(day=21)),
        ],
        scheduled_flight_arrival=SCHEDULED,
        current_ride_eta_min=16,
    )
    assert est.grade == "ride_started"
    assert est.uncertainty_minutes == UNCERTAINTY_RIDE_STARTED


def test_estimate_raises_without_events_or_scheduled():
    with pytest.raises(ValueError):
        estimate_room_arrival([])


# --- place_order_by -----------------------------------------------------------


def test_place_order_by_math():
    """room=12:18, prep=15, courier=12, target=+20 → place by 12:11."""
    room = _t(0, 18).replace(day=21)
    expected = room + timedelta(minutes=20) - timedelta(minutes=DEFAULT_PREP_MIN + DEFAULT_COURIER_MIN)
    assert place_order_by(room) == expected
    assert place_order_by(room) == _t(0, 11).replace(day=21)


def test_place_order_by_respects_overrides():
    room = _t(0, 18).replace(day=21)
    # faster restaurant (prep=5) + slower courier (=15) + later delivery (+30)
    out = place_order_by(room, prep_minutes=5, courier_minutes=15, deliver_after_arrival_min=30)
    expected = room + timedelta(minutes=30) - timedelta(minutes=5 + 15)
    assert out == expected


# --- decide_timing (the wait-vs-act rule) -------------------------------------


def test_decide_waits_when_only_trip_booked():
    """Loose uncertainty (±90) >> cold tolerance (±10) → wait."""
    d = decide_timing(
        [_e("trip_booked", _t(15))],
        now=_t(15, 10),
        scheduled_flight_arrival=SCHEDULED,
    )
    assert d.action == "wait"
    assert "estimate is" in d.reason  # has a real reason
    assert d.estimate.grade == "trip_booked"


def test_decide_still_waits_after_flight_delayed():
    """±50 still > ±10 → wait."""
    d = decide_timing(
        [_e("flight_status", _t(21, 30), status="delayed",
            estimated_arrival=_t(23, 40).isoformat())],
        now=_t(21, 35),
        scheduled_flight_arrival=SCHEDULED,
    )
    assert d.action == "wait"


def test_decide_waits_when_ride_started_but_too_early():
    """Tight estimate but it's not yet place_by-safety_margin → wait."""
    ride_at = _t(0, 5).replace(day=21)
    d = decide_timing(
        [_e("ride_started", ride_at)],
        now=ride_at,                  # right at ride start
        current_ride_eta_min=16,
    )
    # room ≈ 0:33, place_by ≈ 0:33+20-27 = 0:26, safety 3 -> need now>=0:23
    # Right at ride_at (0:05) is well before 0:23 -> wait.
    assert d.action == "wait"
    assert "deadline" in d.reason or "before" in d.reason


def test_decide_acts_when_ride_started_and_inside_safety_window():
    ride_at = _t(0, 5).replace(day=21)
    # advance clock to place_by - 2 min (inside the 3-min safety window)
    d_early = decide_timing(
        [_e("ride_started", ride_at)],
        now=ride_at,
        current_ride_eta_min=16,
    )
    place_by = d_early.place_by
    inside_window = place_by - timedelta(minutes=2)
    d = decide_timing(
        [_e("ride_started", ride_at)],
        now=inside_window,
        current_ride_eta_min=16,
    )
    assert d.action == "act"
    assert d.estimate.grade == "ride_started"
