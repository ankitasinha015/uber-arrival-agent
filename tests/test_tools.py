"""Tool tests — fully hermetic. No network, no API keys, no cost.

The two real tools (eta, restaurants) have their HTTP layer (`get_json`) and key
getters stubbed. The two mock tools (flight, orders) need neither. A separate
live smoke test (test_tools_live.py, gated on real keys) validates the actual
API response shapes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from arrival_agent.core import metrics
from arrival_agent.core.events import Scenario, TripEvent
from arrival_agent.core.tools import eta, flight, orders, restaurants


# --- flight mock (no network) -------------------------------------------------


def _scenario() -> Scenario:
    return Scenario(
        name="t",
        description="t",
        itinerary={"flight_no": "UA1", "scheduled_arrival": "2026-05-20T22:55:00-07:00"},
        envelope={},
        events=[
            TripEvent(type="flight_status", at="2026-05-20T21:30:00-07:00",
                      payload={"status": "delayed", "estimated_arrival": "2026-05-20T23:40:00-07:00"}),
            TripEvent(type="flight_status", at="2026-05-20T23:35:00-07:00",
                      payload={"status": "on_ground", "actual_arrival": "2026-05-20T23:35:00-07:00"}),
        ],
    )


def test_flight_raises_without_active_scenario():
    flight.clear()
    with pytest.raises(RuntimeError):
        flight.get_flight_status("UA1")


def test_flight_returns_scheduled_before_any_event():
    flight.set_active_scenario(_scenario(), now=datetime(2026, 5, 20, 20, 0, tzinfo=timezone.utc))
    out = flight.get_flight_status("UA1")
    assert out["status"] == "scheduled"
    flight.clear()


def test_flight_returns_latest_status_at_or_before_clock():
    sc = _scenario()
    # Clock between the two flight events -> should see 'delayed', not 'on_ground'.
    flight.set_active_scenario(sc, now=datetime(2026, 5, 20, 22, 0, tzinfo=timezone(__import__("datetime").timedelta(hours=-7))))
    out = flight.get_flight_status("UA1")
    assert out["status"] == "delayed"
    # Advance past the second event -> 'on_ground'.
    flight.advance_clock(datetime(2026, 5, 20, 23, 59, tzinfo=timezone(__import__("datetime").timedelta(hours=-7))))
    assert flight.get_flight_status("UA1")["status"] == "on_ground"
    flight.clear()


# --- order mock (no network) --------------------------------------------------


def test_place_order_echoes_picked_option():
    picked = {"restaurant_id": "r1", "restaurant_name": "Lers Ros",
              "items": ["pad see ew"], "est_total": 28, "est_delivery_at": "2026-05-21T00:38:00-07:00"}
    out = orders.place_order(picked)
    assert out["status"] == "placed"
    assert out["restaurant_name"] == "Lers Ros"
    assert out["order_id"].startswith("mock-")


# --- eta (network stubbed) ----------------------------------------------------


def test_geocode_parses_latlng(monkeypatch):
    monkeypatch.setattr(eta, "mapbox_token", lambda: "test")
    monkeypatch.setattr(eta, "get_json", lambda *a, **k: {"features": [{"center": [-122.41, 37.78]}]})
    lat, lng = eta.geocode("Marriott Union Square")
    assert (lat, lng) == (37.78, -122.41)


def test_geocode_raises_when_no_match(monkeypatch):
    monkeypatch.setattr(eta, "mapbox_token", lambda: "test")
    monkeypatch.setattr(eta, "get_json", lambda *a, **k: {"features": []})
    with pytest.raises(LookupError):
        eta.geocode("nowhere at all")


def test_estimate_eta_returns_minutes(monkeypatch):
    monkeypatch.setattr(eta, "mapbox_token", lambda: "test")
    calls = iter([
        {"features": [{"center": [-122.39, 37.62]}]},   # geocode origin (SFO)
        {"features": [{"center": [-122.41, 37.78]}]},   # geocode destination (hotel)
        {"routes": [{"duration": 1500}]},               # directions: 1500s = 25min
    ])
    monkeypatch.setattr(eta, "get_json", lambda *a, **k: next(calls))
    assert eta.estimate_eta("SFO", "Marriott Union Square") == 25


# --- restaurants (network + geocode stubbed) ----------------------------------


def test_get_eats_options_normalizes(monkeypatch):
    monkeypatch.setattr(restaurants, "foursquare_key", lambda: "test")
    monkeypatch.setattr(restaurants, "geocode", lambda near: (37.78, -122.41))
    monkeypatch.setattr(restaurants, "get_json", lambda *a, **k: {"results": [
        {"fsq_place_id": "abc", "name": "Lers Ros", "distance": 320,
         "categories": [{"name": "Thai Restaurant"}],
         "location": {"formatted_address": "730 Larkin St"}},
    ]})
    out = restaurants.get_eats_options("Marriott Union Square")
    assert len(out) == 1
    assert out[0]["restaurant_name"] == "Lers Ros"
    assert out[0]["categories"] == ["Thai Restaurant"]
    assert out[0]["restaurant_id"] == "abc"


# --- metrics instrumentation --------------------------------------------------


def test_metrics_records_tool_calls(monkeypatch):
    monkeypatch.setattr(restaurants, "foursquare_key", lambda: "test")
    monkeypatch.setattr(restaurants, "geocode", lambda near: (37.78, -122.41))
    monkeypatch.setattr(restaurants, "get_json", lambda *a, **k: {"results": []})

    m = metrics.start_run()
    restaurants.get_eats_options("anywhere")
    orders.place_order({"restaurant_name": "x"})
    assert m.tool_calls == 2
    assert m.tool_breakdown["get_eats_options"] == 1
    assert m.tool_breakdown["place_order"] == 1


def test_metrics_noop_when_no_run_active():
    # No start_run() — recording is a silent no-op, tool still works.
    orders.place_order({"restaurant_name": "x"})  # should not raise
