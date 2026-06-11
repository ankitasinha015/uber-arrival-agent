"""Domain: the curation envelope.

Premise 2 made concrete. The user sets a policy envelope ONCE, upfront. The
envelope shapes the agent's *curation* — what counts as a valid candidate
restaurant for this user — not its authority to spend. Money is offstage; the
envelope is purely the agent's filter on what to consider.

Two roles:

  1. ACTIVATION GATE — `should_engage(room_arrival)`. Does the agent act at
     all for this trip? Late-night arrivals match the use case; early-evening
     arrivals don't, so the agent stays quiet.

  2. CANDIDATE FILTER — `filter_candidates(candidates)`. Keeps only the
     candidates that match the user's declared cuisines. If the envelope has
     no cuisine constraint (empty list), every candidate passes.

Cuisine matching is keyword-overlap, case-insensitive: an envelope cuisine
("thai") matches if it appears in any of the candidate's category strings
("Thai Restaurant"). Coarse on purpose — the Chroma taste store (step 3.5)
does the fine-grained re-ranking *within* the filtered set.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DelegationEnvelope(BaseModel):
    """The one-time policy the user sets. The agent operates strictly inside."""

    after_hour: int = 22                 # only act when room_arrival.hour >= this
    max_total: float = 40.0              # USD cap on draft order total
    cuisines: list[str] = Field(default_factory=list)
    no_supply_action: str = "schedule_breakfast"  # graceful degrade target

    # --- activation gate --------------------------------------------------

    def should_engage(self, room_arrival: datetime) -> bool:
        """True when the trip's room-arrival time falls past `after_hour`.

        The arrival being past 10pm is the whole reason this product exists
        (hotel kitchen closed, traveler hungry). A 6pm arrival belongs to a
        different agent (or no agent), so we stay quiet.
        """
        return room_arrival.hour >= self.after_hour or room_arrival.hour < 5
        # the < 5 clause keeps midnight-to-pre-dawn arrivals in scope
        # (00:18 is past after_hour 22 conceptually but hour=0 numerically)

    # --- candidate filter -------------------------------------------------

    def matches_cuisines(self, categories: list[str]) -> bool:
        """True if the candidate's category strings overlap with the envelope
        cuisines (case-insensitive keyword match). No cuisine constraint =>
        everything matches."""
        if not self.cuisines:
            return True
        cats_lc = " ".join(categories).lower()
        return any(c.lower() in cats_lc for c in self.cuisines)

    def filter_candidates(self, candidates: list[dict]) -> list[dict]:
        """Keep candidates whose categories overlap with envelope cuisines.
        Candidates are the normalized dicts from `restaurants.get_eats_options`."""
        return [
            c for c in candidates
            if self.matches_cuisines(c.get("categories", []))
        ]

    # --- price gate (applied later, at draft time) ------------------------

    def allows_total(self, est_total: float | None) -> bool:
        """True if an estimated order total fits the envelope. Unknown total
        (None) is allowed — the choice-set step will price-check before
        surfacing."""
        if est_total is None:
            return True
        return est_total <= self.max_total
