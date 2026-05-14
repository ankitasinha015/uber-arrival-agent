"""The agent-loop contract.

Every framework adapter (LangGraph, raw, ...) implements this same contract against
the same core (tools + domain logic + events). This is what makes the agent
swappable across frameworks — and what makes the framework comparison honest: the
core does not change, only the orchestration around it.

Implementation: TODO.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from arrival_agent.core.events import TripEvent


class AgentDecision:
    """The output of one agent step.

    The agent either WAITS (acting now would fail — e.g. ordering before the ride
    ETA is known) or proposes a DRAFT order for the user to authorize. The decision
    carries its reasoning so the re-timing logic is visible.

    Fields: TODO (action, draft_order, target_time, reasoning, ...).
    """


class ArrivalAgent(ABC):
    """Contract implemented by each framework adapter."""

    @abstractmethod
    def handle_event(self, event: TripEvent) -> AgentDecision:
        """React to a single trip event. Re-predict arrival, re-curate, re-time,
        and decide whether to wait or to surface a draft order."""
        ...

    @abstractmethod
    def state(self) -> dict:
        """Current persisted agent state (last prediction, current draft, envelope).
        Long-running trips span hours — state must survive across events."""
        ...
