"""Tool: draft_order / place_order — MOCKED.

There is no public Uber Eats consumer API, so order placement is necessarily
mocked. This is fine: the artifact demos the *agent*, not a prod integration.

Two operations:
  - draft_order:   build a ready-to-authorize order (the agent does this)
  - place_order:   commit the order — ONLY after the user authorizes payment
                   (Premise 2: predict -> curate -> user authorizes)

Implementation: TODO.
"""

from __future__ import annotations

from datetime import datetime


def draft_order(restaurant: dict, items: list[dict], target_delivery: datetime) -> dict:
    """Build a draft order timed to land at `target_delivery`. Not committed.

    Returns (shape TODO): restaurant, items, total, target_delivery, place_by_time.
    """
    raise NotImplementedError


def place_order(draft: dict) -> dict:
    """Commit a draft order. MUST only be called after explicit user authorization.

    Returns (shape TODO): order_id, status, eta.
    """
    raise NotImplementedError
