"""Domain: the re-timing calculator.

The core of the product. Arrival time is a stack of uncertainties:

    landing -> deplane -> customs/bags -> ride -> check-in -> "20 min after"

The agent cannot predict once. It re-times as each actual arrives, and the
estimate tightens: a flight-status event is a loose estimate; a ride-started
event is a tight one. This module computes, given the events seen so far, the
best current room-arrival estimate and the resulting "place the order by" time.

Implementation: TODO.
"""

from __future__ import annotations

from datetime import datetime

from arrival_agent.core.events import TripEvent


def estimate_room_arrival(events: list[TripEvent]) -> datetime:
    """Best current estimate of when the traveler reaches their hotel room, given
    every trip event seen so far. Tightens as stronger signals arrive.
    """
    raise NotImplementedError


def place_order_by(room_arrival: datetime, prep_minutes: int, courier_minutes: int) -> datetime:
    """Work backwards from desired delivery time to the latest moment the order can
    be placed and still land ~20 min after room arrival.
    """
    raise NotImplementedError


def should_wait(events: list[TripEvent]) -> bool:
    """True if the current estimate is too loose to act on — acting now risks cold
    food at the front desk. Knowing when NOT to act is the hard part.
    """
    raise NotImplementedError
