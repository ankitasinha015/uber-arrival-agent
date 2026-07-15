"""Reservation-vs-delivery: the OpenTable decision (Uber GO-GET Travel Mode).

Uber Travel Mode books reservations AND delivers room service; it doesn't choose between
them. The agent does, reusing the arrival-timing math: make the table and dine out, or
land too late, release it, and switch to room-service delivery."""

from __future__ import annotations

from datetime import datetime

from arrival_agent.web import concierge as C


def _at(hhmm):
    return datetime.strptime(hhmm, "%H:%M")


def test_pure_makes_reservation_both_branches():
    # early domestic arrival: out of the airport well before the table -> make it
    makes, _ = C._makes_reservation(_at("19:40"), C.AIRPORT_EXIT_MIN, "23:00")
    assert makes is True
    # late international arrival: clears customs long after the table -> miss it
    makes, _ = C._makes_reservation(_at("22:55"), C.INTL_EXIT_MIN, "21:00")
    assert makes is False


def test_boundary_is_inclusive():
    # mobile time exactly equals the reservation time -> still makes it
    # 20:05 + exit 35 + travel 20 = 21:00 == the table
    makes, mobile = C._makes_reservation(_at("20:05"), C.AIRPORT_EXIT_MIN, "21:00")
    assert makes is True
    assert mobile == _at("21:00")


def test_lena_releases_and_switches_to_delivery():
    d = C._reservation_decision("lena")
    assert d is not None and d["make"] is False
    booking = C._reservation_booking("lena")
    assert "released" in booking["did"].lower()
    assert "room service" in booking["did"].lower()
    # the release reservation is synced as a booking on a disruption
    bookings, _ = C._trip_extras("lena")
    assert any("reservation" in b["name"].lower() for b in bookings)


def test_no_reservation_no_decision():
    # a traveler without a reservation field yields no decision and no synthesized booking
    assert C._reservation_decision("marcus") is None
