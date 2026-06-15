"""Naive baseline adapter — the strawman, built to be burned.

Same ArrivalAgent contract, deliberately dumb. It orders as soon as the ride
starts, with none of the agent's judgment:

  - No re-timing. It times delivery from `ride_started`, not from a predicted
    room arrival — so in the delayed-flight scenario it orders food that lands
    at the front desk ~7 minutes BEFORE the rider does. Cold food. This is the
    headline flaw the smart agents avoid by *waiting*.
  - No choice-set design. It lists the single nearest restaurant — no LLM call,
    no axis, no taste. (0 LLM calls vs the smart agents' 1.)
  - No envelope filter, no taste ranking, no recovery on order_rejected.

Its only job in this repo is the contrast: `--compare` runs it alongside the
LangGraph and raw adapters so the metrics + the wrong delivery time make the
value of the smart parts concrete.
"""

from __future__ import annotations

from datetime import timedelta

from arrival_agent.core.contract import Action, AgentDecision, ArrivalAgent, ChoiceOption
from arrival_agent.core.events import EventType, Scenario, TripEvent
from arrival_agent.core.tools import orders as orders_mod
from arrival_agent.core.tools import restaurants as restaurants_mod

NAIVE_PREP_MIN = 15
NAIVE_COURIER_MIN = 12


class NaiveArrivalAgent(ArrivalAgent):
    """Orders at ride-start with no timing, no choice set, no recovery."""

    def __init__(self, scenario: Scenario, *, taste_store=None, thread_id: str = "run",
                 ask_first: bool = False):
        # ask_first is accepted for a uniform constructor across adapters but
        # ignored on purpose: the naive baseline never asks, never waits, never
        # curates. That it skips the consent beat too is part of the contrast.
        self._scenario = scenario
        self._hotel = scenario.itinerary.get("hotel", "")
        self._events: list[TripEvent] = []
        self._await = False
        self._option: ChoiceOption | None = None

    def handle_event(self, event: TripEvent) -> AgentDecision:
        self._events.append(event)

        if self._await and event.type == EventType.USER_PICK:
            order = orders_mod.place_order(self._option.model_dump(mode="json"))
            self._await = False
            return AgentDecision(
                action=Action.PLACED,
                reasoning=f"order placed at {self._option.restaurant_name} (naive: timed from ride start)",
                placed_option_id=self._option.option_id,
            )

        # Act the moment the ride starts — no waiting, no re-timing.
        if not self._await and event.type == EventType.RIDE_STARTED:
            results = restaurants_mod.get_eats_options(self._hotel, limit=5)
            if not results:
                return AgentDecision(action=Action.WAIT, reasoning="naive: no restaurants found")
            nearest = results[0]
            deliver_at = event.at + timedelta(minutes=NAIVE_PREP_MIN + NAIVE_COURIER_MIN)
            self._option = ChoiceOption(
                option_id="opt-1",
                restaurant_id=nearest["restaurant_id"],
                restaurant_name=nearest["restaurant_name"],
                items=["Most popular"],
                est_total=25.0,
                est_delivery_at=deliver_at,
                cuisine_tags=list(nearest.get("categories", [])),
                why_this_one="Nearest open restaurant",
            )
            self._await = True
            return AgentDecision(
                action=Action.SURFACE,
                reasoning="naive baseline: ordering now from the nearest place (no re-timing, no choice)",
                room_arrival_estimate=None,
                axis=None,
                choice_set=[self._option],
                why_these="Nearest open restaurant.",
            )

        return AgentDecision(action=Action.WAIT, reasoning="naive: waiting for ride to start")

    def state(self) -> dict:
        return {"events": [e.model_dump(mode="json") for e in self._events], "awaiting_pick": self._await}
