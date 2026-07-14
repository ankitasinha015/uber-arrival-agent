"""Arrival transport: exactly ONE way to the hotel, and never one the traveler
already has. The agent knows each traveler's existing bookings, so it must not offer
to book an Uber when a pre-booked ride, a rental, or a greeter/pickup already covers
the airport→hotel leg. (Regression: Priya has a Meet & Greet pickup — offering an Uber
on top of it is the agent contradicting its own trip data.)"""

from __future__ import annotations

from arrival_agent.web import concierge as C


def _branch(mode: str) -> str:
    if C._uber_ride(mode):
        return "track"        # pre-booked Uber → hand off to live tracking
    if C._rental_car(mode):
        return "rental"       # driving themselves
    if C._ground_pickup(mode):
        return "pickup"       # greeter / car service already meeting them
    return "book"             # genuinely needs a ride → offer to book one


def test_each_persona_gets_exactly_the_right_transport():
    assert _branch("priya") == "pickup"    # Meet & Greet — must NOT offer an Uber
    assert _branch("dev") == "track"       # pre-booked Uber Reserve
    assert _branch("marcus") == "rental"   # Hertz rental
    assert _branch("olivia") == "book"     # no arrival transport → offer a ride
    assert _branch("lena") == "book"       # only a dinner reservation, no transport


def test_pickup_traveler_is_not_offered_a_ride():
    # the "book-ride" todo (the "Book my ride" card) fires only in the "book" branch.
    assert _branch("priya") != "book"
    pickup = C._ground_pickup("priya")
    assert pickup and "pickup" in pickup["name"].lower()


def test_ground_pickup_ignores_uber_and_rental_bookings():
    # a pre-booked Uber is tracked, a rental is driven — neither counts as a "pickup"
    # arrangement, so _ground_pickup must leave them to their own handlers.
    assert C._ground_pickup("dev") is None
    assert C._ground_pickup("marcus") is None
