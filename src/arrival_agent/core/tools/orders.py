"""Tool: place_order — MOCKED.

There is no public Uber Eats consumer API, so order placement is necessarily
mocked. This is fine: the artifact demos the *agent*, not a prod integration.

The agent never commits an order on its own. The user picks one of the 2-3
options the agent surfaces, and the pick IS the placement. Payment is offstage
(Uber's existing card-on-file plumbing) and out of scope for this artifact —
there is no separate authorize step, no spend UI, no money mechanics. The user
takes the final call by choosing; everything else is the agent.

Implementation: TODO.
"""

from __future__ import annotations


def place_order(picked_option: dict) -> dict:
    """Place the order the user picked from the agent's choice set.

    Called when the user taps one of the 2-3 surfaced options. The pick IS
    the terminal action — there is no separate authorize step.

    Returns (shape TODO): order_id, status, eta, restaurant, items, total.
    """
    raise NotImplementedError
