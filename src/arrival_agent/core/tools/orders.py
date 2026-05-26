"""Tool: place_order — MOCKED.

There is no public Uber Eats consumer API, so order placement is necessarily
mocked. This is fine: the artifact demos the *agent*, not a prod integration.

The agent never commits an order on its own. The user picks one of the 2-3
options the agent surfaces, and the pick IS the placement. Payment is offstage
(Uber's existing card-on-file plumbing) and out of scope — no authorize step,
no spend UI, no money mechanics. The user takes the final call by choosing.
"""

from __future__ import annotations

from uuid import uuid4

from arrival_agent.core.metrics import instrumented


@instrumented("place_order")
def place_order(picked_option: dict) -> dict:
    """Place the order the user picked from the agent's choice set.

    Called when the user taps one of the surfaced options. The pick IS the
    terminal action — there is no separate authorize step.

    Returns a mock confirmation echoing the picked option.
    """
    return {
        "order_id": f"mock-{uuid4().hex[:8]}",
        "status": "placed",
        "restaurant_id": picked_option.get("restaurant_id"),
        "restaurant_name": picked_option.get("restaurant_name"),
        "items": picked_option.get("items", []),
        "total": picked_option.get("est_total"),
        "eta": picked_option.get("est_delivery_at"),
    }
