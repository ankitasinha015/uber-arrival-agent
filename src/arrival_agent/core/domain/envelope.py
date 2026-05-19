"""Domain: the curation envelope.

Premise 2 made concrete. The user sets a policy envelope ONCE, upfront. The
envelope shapes the agent's *curation* — what counts as a valid candidate
restaurant for this user — not its authority to spend. Money is offstage; the
envelope is purely the agent's filter on what to consider.

The agent acts freely within the envelope (curating, re-timing, recovering) and
stops at the choice moment: it surfaces 2-3 in-envelope options and the user
picks one. The pick is the terminal action — no separate authorize step.

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
