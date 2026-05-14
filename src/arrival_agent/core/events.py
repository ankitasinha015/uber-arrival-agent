"""Event model for the arrival agent.

The agent is event-driven. It does not run on a fixed schedule — it wakes when a
trip event arrives, re-evaluates, and decides whether to act or wait. These are the
events it reacts to.

Implementation: TODO.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class EventType(str, Enum):
    """Trip events that wake the agent."""

    TRIP_BOOKED = "trip_booked"          # itinerary registered (flight + hotel)
    FLIGHT_STATUS = "flight_status"      # flight delayed / on-ground (mocked source)
    RIDE_STARTED = "ride_started"        # rider in the car — tight ETA available
    RIDE_ENDED = "ride_ended"            # rider at the hotel
    ORDER_REJECTED = "order_rejected"    # restaurant went offline — triggers recovery
    CHECK_IN = "check_in"                # rider checked in — the "20 min after" anchor


class TripEvent(BaseModel):
    """A single event in the trip timeline."""

    type: EventType
    at: datetime
    payload: dict  # event-specific data; shape TODO per type


# TODO: scenario loader — read scenarios/*.json into an ordered list of TripEvents
# so the demo can replay a delayed-flight timeline against the agent.
