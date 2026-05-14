"""Domain: recovery policy.

Two failure paths the demo must handle gracefully:

  1. ORDER_REJECTED — a restaurant goes offline after being chosen (common late at
     night). The agent re-curates and re-times against the next-best option,
     without bothering the user — it is still within the delegation envelope.

  2. NO_SUPPLY — nothing good is open near the hotel at the target time. The agent
     does not fail silently; it degrades gracefully ("nothing good is open near
     your hotel that late — want breakfast scheduled for 7am instead?").

Implementation: TODO.
"""

from __future__ import annotations


def recover_from_rejection(rejected: dict, candidates: list[dict]) -> dict | None:
    """Pick the next-best open option after a rejection. None if none remain."""
    raise NotImplementedError


def no_supply_fallback(hotel: str, target) -> dict:
    """Build a graceful alternative when nothing is open at the target time
    (e.g. a scheduled breakfast). Shape: TODO.
    """
    raise NotImplementedError
