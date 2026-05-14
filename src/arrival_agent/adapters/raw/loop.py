"""Raw adapter — the CONTRAST implementation.

Same agent, same core, no orchestration framework. A hand-built tool-calling loop
with hand-rolled state persistence and a manual "pause for authorization" step.

The point is the comparison: building this exposes exactly what LangGraph gives you
for free — checkpointing, interrupts, the state machine — and what it costs you in
return (a dependency, a mental model). That tradeoff, made concrete, is the
interview insight.

This adapter implements core.contract.ArrivalAgent with a plain loop.

Implementation: TODO.
"""

from __future__ import annotations

from arrival_agent.core.contract import AgentDecision, ArrivalAgent
from arrival_agent.core.events import TripEvent


class RawArrivalAgent(ArrivalAgent):
    """ArrivalAgent backed by a hand-built tool-calling loop."""

    def handle_event(self, event: TripEvent) -> AgentDecision:  # TODO
        raise NotImplementedError

    def state(self) -> dict:  # TODO — hand-rolled persistence (json file / dict)
        raise NotImplementedError
