"""LangGraph adapter — the PRIMARY implementation.

Why LangGraph is the best fit for this project:
  - Long-running, event-driven, stateful: the trip spans hours and the agent must
    persist state across events. LangGraph state + checkpointing maps directly.
  - "Wait for ride-started, then re-decide" is a graph transition, not a chat turn.
  - "User authorizes payment" is a native LangGraph interrupt — the graph pauses at
    the spend boundary and resumes on authorization.

This adapter implements core.contract.ArrivalAgent using a LangGraph StateGraph.
The nodes call the same core tools and domain logic every other adapter uses.

Sketch of the graph (Implementation: TODO):
    [on_event] -> [predict_arrival] -> [should_wait?]
        wait  -> END (persist state, sleep until next event)
        act   -> [curate] -> [draft_order] -> [interrupt: authorize] -> [place_order]
    [order_rejected] -> [recover] -> [curate] ...
"""

from __future__ import annotations

from arrival_agent.core.contract import AgentDecision, ArrivalAgent
from arrival_agent.core.events import TripEvent


class LangGraphArrivalAgent(ArrivalAgent):
    """ArrivalAgent backed by a LangGraph StateGraph with checkpointing."""

    def handle_event(self, event: TripEvent) -> AgentDecision:  # TODO
        raise NotImplementedError

    def state(self) -> dict:  # TODO — backed by the LangGraph checkpointer
        raise NotImplementedError
