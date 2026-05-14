"""Domain: the delegation envelope.

Premise 2 made concrete. The user delegates ONCE, upfront, by setting a policy
envelope. The agent then acts freely *within* that envelope — curating, re-timing,
recovering — and only stops at the boundary the envelope defines: spending money.
At that boundary it surfaces a draft for the user to authorize.

The envelope is what makes "the agent does the work" safe. It is not a weaker
agent; it is scoped delegation.

Example envelope:
    after_hour: 22                  # only act for arrivals past 10pm
    max_total: 40                   # stay under $40
    cuisines: ["thai", "indian"]    # taste constraints
    no_supply_action: "schedule_breakfast"

Implementation: TODO.
"""

from __future__ import annotations

from pydantic import BaseModel


class DelegationEnvelope(BaseModel):
    """The one-time policy the user sets. The agent operates strictly inside it."""

    after_hour: int = 22
    max_total: int = 40
    cuisines: list[str] = []
    no_supply_action: str = "schedule_breakfast"

    # TODO: validation, and an `allows(draft) -> bool` check the agent runs before
    # surfacing any draft order for authorization.
