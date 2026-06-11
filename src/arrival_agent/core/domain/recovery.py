"""Domain: recovery policy.

Two failure paths the demo must handle gracefully:

  1. ORDER_REJECTED — a restaurant goes offline mid-stream (or during the
     window between when the agent picked it and when the order would be
     placed). The agent re-curates without re-bothering the user — they're
     still within the envelope they delegated.

  2. NO_SUPPLY — nothing open near the hotel at the target time. The agent
     does not fail silently; it surfaces a graceful alternative (breakfast
     scheduled for 7am the next morning by default).

These functions are pure — no I/O. The adapter calls them with already-
filtered candidates.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta


def recover_from_rejection(
    rejected: dict,
    remaining_candidates: list[dict],
) -> dict | None:
    """Pick the next-best candidate after a restaurant goes offline.

    `remaining_candidates` is the in-envelope candidate set EXCLUDING the
    rejected one (the adapter is responsible for the exclusion — it knows
    the rest of its state). Returns the next candidate, or None when the
    list is empty (caller then triggers no-supply fallback).
    """
    if not remaining_candidates:
        return None
    return remaining_candidates[0]


def no_supply_fallback(
    hotel: str,
    target_room_arrival: datetime,
    *,
    breakfast_hour: int = 7,
) -> dict:
    """Build a graceful alternative when nothing is open at the target time.

    Schedules a breakfast order for the next morning. Returns a dict shaped
    like a choice option so the adapter can surface it the same way it
    surfaces normal choice sets — same UI, different message.
    """
    # next calendar day at breakfast_hour:00 local
    next_day = (target_room_arrival + timedelta(days=1)).date()
    breakfast_at = datetime.combine(
        next_day,
        time(hour=breakfast_hour, minute=0),
        tzinfo=target_room_arrival.tzinfo,
    )
    return {
        "kind": "breakfast_fallback",
        "hotel": hotel,
        "deliver_at": breakfast_at,
        "reason": (
            f"Nothing in your envelope is open near {hotel} at "
            f"{target_room_arrival:%H:%M}. Want breakfast scheduled "
            f"for {breakfast_at:%H:%M} instead?"
        ),
    }
