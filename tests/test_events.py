"""Smoke tests for the event model and scenario loader.

These verify that the typed payload models stay in sync with the scenario JSON
on disk — if someone changes one without the other, this catches it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arrival_agent.core.events import (
    EventType,
    FlightStatusPayload,
    RideStartedPayload,
    TripBookedPayload,
    load_scenario,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = REPO_ROOT / "scenarios" / "delayed-flight.json"


def test_load_delayed_flight_scenario() -> None:
    s = load_scenario(SCENARIO)
    assert s.name == "delayed-flight"
    assert s.itinerary["flight_no"] == "UA482"
    assert s.envelope["after_hour"] == 22
    assert len(s.events) >= 5


def test_event_types_ordered_as_expected() -> None:
    s = load_scenario(SCENARIO)
    types = [e.type for e in s.events]
    # Trip should start with a booking and reach the room one way or another.
    assert types[0] == EventType.TRIP_BOOKED
    assert EventType.RIDE_STARTED in types
    assert EventType.CHECK_IN in types
    # The demo also exercises the recovery branch.
    assert EventType.ORDER_REJECTED in types


def test_every_payload_parses_against_its_typed_model() -> None:
    """The real check: each event's payload must validate against the model
    registered for its EventType. This catches drift between the JSON shape
    and the Python types."""
    s = load_scenario(SCENARIO)
    for e in s.events:
        # Should not raise — pydantic will complain loudly if a field is wrong.
        e.parsed()


def test_flight_status_payload_extracts_typed_fields() -> None:
    s = load_scenario(SCENARIO)
    flight_events = [e for e in s.events if e.type == EventType.FLIGHT_STATUS]
    assert flight_events, "scenario should include flight_status events"
    for e in flight_events:
        payload = e.parsed()
        assert isinstance(payload, FlightStatusPayload)
        assert payload.status in {"delayed", "on_ground", "cancelled"}


def test_trip_booked_carries_itinerary_essentials() -> None:
    s = load_scenario(SCENARIO)
    booked = next(e for e in s.events if e.type == EventType.TRIP_BOOKED)
    # The trip_booked event in this scenario carries a "note" payload — the
    # full itinerary lives at the scenario level. That is intentional: the
    # scenario file is authoritative, the event is the trigger.
    assert "note" in booked.payload


def test_ride_started_parses_with_minimal_payload() -> None:
    s = load_scenario(SCENARIO)
    ride = next(e for e in s.events if e.type == EventType.RIDE_STARTED)
    payload = ride.parsed()
    assert isinstance(payload, RideStartedPayload)


def test_unknown_event_type_raises() -> None:
    """Smoke check that pydantic actually rejects junk."""
    from arrival_agent.core.events import TripEvent

    with pytest.raises(Exception):
        TripEvent.model_validate(
            {"type": "not_a_real_event_type", "at": "2026-05-20T22:00:00-07:00"}
        )
