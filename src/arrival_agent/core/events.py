"""Event model for the arrival agent.

The agent is event-driven. It does not run on a fixed schedule — it wakes when a
trip event arrives, re-evaluates, and decides whether to act or wait. These are
the events it reacts to, and the scenario loader for replaying mock timelines
from `scenarios/*.json`.

Wire format on disk (one event in scenarios/delayed-flight.json):

    {
      "type": "flight_status",
      "at":   "2026-05-20T23:35:00-07:00",
      "payload": { "status": "on_ground", "actual_arrival": "..." }
    }

Per-type `*Payload` models parse the `payload` dict into typed fields when the
agent reaches for them. Keeping `payload: dict` on `TripEvent` itself means the
scenario JSON stays loose and forward-compatible; the typed payload models are
the contract for *reading* events inside the agent.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Trip events that wake the agent.

    Ordered loosely by when they typically fire in a trip. The agent's
    re-timing precision improves monotonically as later events arrive —
    a flight_status estimate is loose; a ride_started estimate is tight.
    """

    TRIP_BOOKED = "trip_booked"          # itinerary registered, agent starts watching
    FLIGHT_STATUS = "flight_status"      # delayed / on_ground (mocked source)
    RIDE_STARTED = "ride_started"        # rider in the car — tight ETA available
    RIDE_ENDED = "ride_ended"            # rider at the hotel
    ORDER_REJECTED = "order_rejected"    # restaurant went offline — recovery branch
    CHECK_IN = "check_in"                # rider checked in — anchor for "20 min after"
    USER_CONSENT = "user_consent"        # user answered the opt-in ask (yes/no)
    USER_PICK = "user_pick"              # user picked one of the surfaced options


# --- typed payload models -----------------------------------------------------
#
# Each event type has a payload schema. These exist so the agent reads typed
# fields, not stringly-typed dict keys. TripEvent itself still carries an
# untyped `payload: dict` to stay close to the JSON wire format; call
# `event.parsed()` to get the right payload model.


class TripBookedPayload(BaseModel):
    """The trip_booked event is the trigger that starts the agent watching;
    the actual itinerary fields (flight_no, scheduled_arrival, airport, hotel)
    live at the scenario level (`Scenario.itinerary`), not on this event.
    Keeping them in one place avoids drift."""

    note: str | None = None


class FlightStatusPayload(BaseModel):
    status: str  # "delayed" | "on_ground" | "cancelled"
    estimated_arrival: datetime | None = None
    actual_arrival: datetime | None = None


class RideStartedPayload(BaseModel):
    note: str | None = None
    # Live traffic ETA is fetched via the eta tool on demand, not carried here.


class RideEndedPayload(BaseModel):
    note: str | None = None


class OrderRejectedPayload(BaseModel):
    reason: str
    rejected_restaurant_id: str | None = None
    note: str | None = None


class CheckInPayload(BaseModel):
    note: str | None = None


class UserConsentPayload(BaseModel):
    """The user answered the agent's opt-in ask. `consent=True` lets the agent
    proceed (predict → curate → surface); `consent=False` sends it dormant for
    the rest of the trip. Arrives only after the agent emitted an ASK."""

    consent: bool


class UserPickPayload(BaseModel):
    """The user picked one of the agent's surfaced options. This event is the
    terminal trigger — the agent places the picked order and the loop ends."""

    option_id: str


_PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.TRIP_BOOKED: TripBookedPayload,
    EventType.FLIGHT_STATUS: FlightStatusPayload,
    EventType.RIDE_STARTED: RideStartedPayload,
    EventType.RIDE_ENDED: RideEndedPayload,
    EventType.ORDER_REJECTED: OrderRejectedPayload,
    EventType.CHECK_IN: CheckInPayload,
    EventType.USER_CONSENT: UserConsentPayload,
    EventType.USER_PICK: UserPickPayload,
}


# --- the event itself ---------------------------------------------------------


class TripEvent(BaseModel):
    """A single event in the trip timeline.

    `payload` stays as a dict to match the JSON wire format. Use `.parsed()` to
    get the typed payload model for `self.type`.
    """

    type: EventType
    at: datetime
    payload: dict = Field(default_factory=dict)

    def parsed(self) -> BaseModel:
        """Return the typed payload model for this event's type."""
        model = _PAYLOAD_MODELS[self.type]
        return model.model_validate(self.payload)


# --- scenario loader ----------------------------------------------------------


class Scenario(BaseModel):
    """A mock trip timeline replayed against the agent for demos and tests."""

    name: str
    description: str
    itinerary: dict
    envelope: dict
    events: list[TripEvent]


def load_scenario(path: str | Path) -> Scenario:
    """Load a scenario JSON file from disk. The default scenarios live in
    `scenarios/` at the repo root."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return Scenario.model_validate(raw)
