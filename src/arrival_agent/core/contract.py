"""The agent-loop contract.

Every framework adapter (LangGraph, raw, ...) implements this same contract
against the same core (tools + domain logic + events). This is what makes the
agent swappable across frameworks — and what makes the framework comparison
honest: the core does not change, only the orchestration around it.

The agent's job at every step:

    handle_event(event) -> AgentDecision

The decision is either WAIT (current estimate is too loose to act, or it is not
yet time, or supply is missing) or SURFACE (here are 2-3 meaningfully different
options for the user to pick from). The user's pick arrives as its own event
(USER_PICK) which terminates the loop.

`AgentDecision.reasoning` is mandatory — the demo's value is the visible
"why," not the answer. Every wait and every surface must come with the
agent's stated rationale.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from arrival_agent.core.events import TripEvent


class Action(str, Enum):
    """What the agent decided to do at this step."""

    WAIT = "wait"          # current estimate too loose, or not yet time, or no supply
    SURFACE = "surface"    # surface a choice set to the user
    PLACED = "placed"      # user picked; order has been placed (terminal)


class ChoiceAxis(str, Enum):
    """The axis of difference the agent chose when designing the choice set.

    The most agentic moment in the product. Picking ONE restaurant is search;
    picking three restaurants that vary along an axis that matters for this
    user at this moment is judgment.
    """

    CUISINE = "cuisine"                          # Thai / Indian / Pizza
    SPEED_VS_QUALITY = "speed_vs_quality"        # fast / best fit / cheap
    FAMILIARITY_VS_NOVELTY = "familiarity_vs_novelty"  # usual / new highly-rated / light
    VOLUME = "volume"                            # snack / real meal / comfort feast


class ChoiceOption(BaseModel):
    """One card in the surfaced choice set.

    The agent picks 2-3 of these representing distinct values along the chosen
    axis. The user picks one and the order is placed for that option.
    """

    option_id: str
    restaurant_id: str
    restaurant_name: str
    items: list[str]
    est_total: float
    # Optional: filled by the adapter from the current room-arrival estimate.
    # Choice-set design may run before the adapter has a delivery target locked.
    est_delivery_at: datetime | None = None
    cuisine_tags: list[str] = Field(default_factory=list)
    why_this_one: str  # the agent's one-line rationale for including THIS option


class AgentDecision(BaseModel):
    """The output of one agent step.

    Fields are populated per `action`:
      - WAIT:    reasoning + room_arrival_estimate (loose is fine, just be honest)
      - SURFACE: reasoning + room_arrival_estimate + axis + choice_set + why_these
      - PLACED:  reasoning + placed_option_id
    """

    action: Action
    reasoning: str
    room_arrival_estimate: datetime | None = None

    # SURFACE only
    axis: ChoiceAxis | None = None
    choice_set: list[ChoiceOption] = Field(default_factory=list)
    why_these: str | None = None  # one-line meta-rationale for the SET

    # PLACED only
    placed_option_id: str | None = None


class ArrivalAgent(ABC):
    """Contract implemented by each framework adapter.

    Adapters wrap the same core tools + domain logic in their orchestration
    model (LangGraph state machine, hand-built loop, ...). Outside the adapter
    nothing should care which one is running.
    """

    @abstractmethod
    def handle_event(self, event: TripEvent) -> AgentDecision:
        """React to a single trip event. Re-predict arrival, re-curate if
        needed, and decide whether to wait or surface a choice set. If the
        event is a USER_PICK, place the picked order and return Action.PLACED."""
        ...

    @abstractmethod
    def state(self) -> dict:
        """Current persisted agent state — last prediction, current draft
        choice set, envelope, events seen so far. Long-running trips span
        hours; state must survive across events. LangGraph adapter backs this
        with its checkpointer; the raw adapter rolls its own."""
        ...
