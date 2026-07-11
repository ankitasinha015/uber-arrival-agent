"""Phase 3 — mock email tool + booking-email -> itinerary extraction.

Both are mocked like flight/orders: the send is a mock confirmation, the extract
falls back to a deterministic parse offline. No network in these tests.
"""

from __future__ import annotations

from arrival_agent.core import metrics
from arrival_agent.core.domain.itinerary import extract_itinerary, sample_booking_email
from arrival_agent.core.tools.email import send_hotel_note


def test_send_hotel_note_confirms():
    metrics.start_run()
    r = send_hotel_note("Hotel Zephyr", "Arriving ~1:15 AM, please hold the room.")
    assert r["status"] == "sent"
    assert r["to"] == "Hotel Zephyr"
    assert "hold the room" in r["note"]


def test_send_is_instrumented():
    m = metrics.start_run()
    send_hotel_note("Hotel Zephyr", "note")
    assert m.tool_calls >= 1  # counts as a tool call like the other mocks


def test_extract_itinerary_from_booking_email():
    it = extract_itinerary(sample_booking_email(), use_llm=False)
    assert it["flight_no"] == "UA 517"
    assert it["airport"] == "SFO"
    assert it["hotel"] == "Hotel Zephyr, San Francisco"
    assert it["scheduled_arrival"] == "2026-05-20T23:15:00-07:00"


def test_extracted_shape_is_a_scenario_itinerary_dropin():
    it = extract_itinerary(sample_booking_email(), use_llm=False)
    # the adapters read hotel / airport / scheduled_arrival off scenario.itinerary
    for key in ("hotel", "airport", "scheduled_arrival"):
        assert it.get(key)
