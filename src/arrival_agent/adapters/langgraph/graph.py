"""LangGraph adapter — the PRIMARY implementation.

Why LangGraph is the best fit for this project:
  - Long-running, event-driven, stateful: the trip spans hours and the agent
    must persist state across events. LangGraph state + checkpointing maps
    directly: each trip event is one graph invocation on the same thread, and
    the checkpointer carries everything the agent knows between wakes.
  - "Wait for ride-started, then re-decide" is a conditional edge, not a chat
    turn.
  - "Surface the choice set and wait for the user's pick" is a NATIVE
    LangGraph interrupt — the graph pauses at the choice moment and resumes
    on the pick. The pick IS the terminal action; no separate authorize step.

The graph:

    START -> ingest -> predict -> [timing?]
                          wait  -> record_wait -> END
                          act   -> curate -> [supply?]
                                      none -> no_supply -> END
                                      some -> design -> surface -> place -> END
                                                          ^
                                                INTERRUPT lives here.
                                                The surface node loops:
                                                  pick           -> proceed to place
                                                  order_rejected -> deterministic
                                                                    recovery, re-surface
                                                  other event    -> acknowledge, keep waiting

Replay-safety note: when an interrupted node resumes, LangGraph re-runs the
node from the top, replaying previous interrupt answers in order. That is why
`design` (the LLM call) is its OWN node — its output is checkpointed before
`surface` runs, so the LLM is never re-invoked by resume replays. Everything
inside `surface` is deterministic on (state, answer-sequence).
"""

from __future__ import annotations

import operator
from datetime import datetime, timedelta
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from arrival_agent.core.contract import (
    Action,
    AgentDecision,
    ArrivalAgent,
    ChoiceAxis,
    ChoiceOption,
)
from arrival_agent.core.domain import choice_set as choice_set_mod
from arrival_agent.core.domain.envelope import DelegationEnvelope
from arrival_agent.core.domain.recovery import no_supply_fallback, recover_from_rejection
from arrival_agent.core.domain.retiming import decide_timing
from arrival_agent.core.events import EventType, Scenario, TripEvent
from arrival_agent.core.tools import eta as eta_mod
from arrival_agent.core.tools import orders as orders_mod
from arrival_agent.core.tools import restaurants as restaurants_mod

# Surface the choice set as soon as the estimate is tight — the human needs
# time to pick before the place-by deadline (see retiming.decide_timing).
USER_RESPONSE_BUFFER_MIN = 20.0
DELIVER_AFTER_ARRIVAL_MIN = 20


class GraphState(TypedDict, total=False):
    """Checkpointed agent state. `events` accumulates across invocations."""

    events: Annotated[list[dict], operator.add]
    ride_eta_min: int | None
    timing: dict | None            # latest decide_timing result, serialized
    candidates: list[dict]         # post-envelope (or relaxed) candidate pool
    curation_note: str | None      # e.g. "envelope relaxed" — surfaced in reasoning
    choice_payload: dict | None    # serialized choice set handed to the interrupt
    picked_option_id: str | None
    order: dict | None
    decision: dict | None          # terminal decision for non-interrupted runs


def _option_dict(o: ChoiceOption) -> dict:
    d = o.model_dump()
    if isinstance(d.get("est_delivery_at"), datetime):
        d["est_delivery_at"] = d["est_delivery_at"].isoformat()
    return d


class LangGraphArrivalAgent(ArrivalAgent):
    """ArrivalAgent backed by a LangGraph StateGraph with checkpointing."""

    def __init__(
        self,
        scenario: Scenario,
        *,
        taste_store=None,
        thread_id: str = "run",
    ):
        self._scenario = scenario
        self._envelope = DelegationEnvelope(**scenario.envelope)
        self._hotel: str = scenario.itinerary.get("hotel", "")
        self._airport: str = scenario.itinerary.get("airport", "")
        sched = scenario.itinerary.get("scheduled_arrival")
        self._scheduled_arrival = (
            datetime.fromisoformat(sched) if isinstance(sched, str) else sched
        )
        self._taste = taste_store
        self._user_id = scenario.itinerary.get("user_id")
        self._config = {"configurable": {"thread_id": thread_id}}
        self._awaiting_pick = False
        self._graph = self._build()

    # --- graph construction -------------------------------------------------

    def _build(self):
        g = StateGraph(GraphState)
        g.add_node("predict", self._predict)
        g.add_node("record_wait", self._record_wait)
        g.add_node("curate", self._curate)
        g.add_node("no_supply", self._no_supply)
        g.add_node("design", self._design)
        g.add_node("surface", self._surface)
        g.add_node("place", self._place)

        g.add_edge(START, "predict")
        g.add_conditional_edges(
            "predict",
            lambda s: "act" if (s.get("timing") or {}).get("action") == "act" else "wait",
            {"wait": "record_wait", "act": "curate"},
        )
        g.add_edge("record_wait", END)
        g.add_conditional_edges(
            "curate",
            lambda s: "some" if s.get("candidates") else "none",
            {"none": "no_supply", "some": "design"},
        )
        g.add_edge("no_supply", END)
        g.add_edge("design", "surface")
        g.add_edge("surface", "place")
        g.add_edge("place", END)
        return g.compile(checkpointer=MemorySaver())

    # --- helpers --------------------------------------------------------------

    def _trip_events(self, state: GraphState) -> list[TripEvent]:
        return [TripEvent.model_validate(e) for e in state.get("events", [])]

    # --- nodes ----------------------------------------------------------------

    def _predict(self, state: GraphState) -> dict:
        events = self._trip_events(state)
        now = max(e.at for e in events)

        # First time the ride starts, fetch a live ETA (instrumented tool call).
        ride_eta = state.get("ride_eta_min")
        eta_note = None
        if ride_eta is None and any(e.type == EventType.RIDE_STARTED for e in events):
            try:
                ride_eta = eta_mod.estimate_eta(self._airport, self._hotel)
            except Exception as e:
                # A geocoding/routing hiccup must degrade, not kill the trip.
                # decide_timing falls back to DEFAULT_RIDE_MIN when eta is None;
                # we cache a sentinel so we don't re-hit the API every event.
                ride_eta = -1
                eta_note = f"live ETA unavailable ({type(e).__name__}) — using default ride time"
        effective_eta = None if (ride_eta is None or ride_eta < 0) else ride_eta

        timing = decide_timing(
            events,
            now=now,
            scheduled_flight_arrival=self._scheduled_arrival,
            current_ride_eta_min=effective_eta,
            deliver_after_arrival_min=DELIVER_AFTER_ARRIVAL_MIN,
            user_response_buffer_min=USER_RESPONSE_BUFFER_MIN,
        )
        room_arrival = timing.estimate.estimated_at

        action = timing.action
        reason = timing.reason if eta_note is None else f"{timing.reason} ({eta_note})"
        # Activation gate: the product only exists for late-night arrivals.
        if action == "act" and not self._envelope.should_engage(room_arrival):
            action, reason = "wait", (
                f"room arrival {room_arrival:%H:%M} is outside the late-night "
                f"window (after_hour={self._envelope.after_hour}) — staying quiet"
            )

        return {
            "ride_eta_min": ride_eta,
            "timing": {
                "action": action,
                "reason": reason,
                "room_arrival": room_arrival.isoformat(),
                "uncertainty_min": timing.estimate.uncertainty_minutes,
                "grade": timing.estimate.grade,
                "place_by": timing.place_by.isoformat(),
            },
        }

    def _record_wait(self, state: GraphState) -> dict:
        t = state["timing"]
        return {
            "decision": {
                "action": "wait",
                "reasoning": t["reason"],
                "room_arrival": t["room_arrival"],
            }
        }

    def _curate(self, state: GraphState) -> dict:
        raw = restaurants_mod.get_eats_options(self._hotel, limit=10)
        filtered = self._envelope.filter_candidates(raw)
        note = None
        if len(filtered) < 2 and raw:
            # Honest relaxation beats an empty choice set: surface nearby
            # alternatives and SAY the envelope was relaxed.
            note = (
                f"only {len(filtered)} candidate(s) matched your cuisines "
                f"({', '.join(self._envelope.cuisines)}) — showing nearby alternatives"
                if self._envelope.cuisines
                else None
            )
            filtered = raw
        if self._taste is not None and self._user_id:
            filtered = self._taste.rank_candidates(self._user_id, filtered)
        return {"candidates": filtered, "curation_note": note}

    def _no_supply(self, state: GraphState) -> dict:
        t = state["timing"]
        room_arrival = datetime.fromisoformat(t["room_arrival"])
        fb = no_supply_fallback(self._hotel, room_arrival)
        return {
            "decision": {
                "action": "surface",
                "reasoning": fb["reason"],
                "room_arrival": t["room_arrival"],
                "fallback": {
                    "option_id": "opt-breakfast",
                    "restaurant_id": "breakfast-fallback",
                    "restaurant_name": "Scheduled breakfast",
                    "items": ["Breakfast delivery"],
                    "est_total": 0.0,
                    "est_delivery_at": fb["deliver_at"].isoformat(),
                    "cuisine_tags": [],
                    "why_this_one": fb["reason"],
                },
            }
        }

    def _design(self, state: GraphState) -> dict:
        t = state["timing"]
        room_arrival = datetime.fromisoformat(t["room_arrival"])
        deliver_at = room_arrival + timedelta(minutes=DELIVER_AFTER_ARRIVAL_MIN)
        context = {
            "time_of_day": f"{room_arrival:%H:%M} (room arrival estimate)",
            "city": self._hotel,
            "fatigue": "high — late-night arrival after a flight",
        }
        past = (
            self._taste.recent_picks(self._user_id)
            if (self._taste is not None and self._user_id)
            else None
        )
        candidates = state["candidates"][:8]
        try:
            cs = choice_set_mod.design_choice_set(candidates, context, past_picks=past)
            options, axis = cs.options, cs.axis
            axis_reason, why_these = cs.axis_reason, cs.why_these
        except Exception as e:  # LLM failure -> deterministic, VISIBLE fallback
            options = [
                ChoiceOption(
                    option_id=f"opt-{i + 1}",
                    restaurant_id=c["restaurant_id"],
                    restaurant_name=c["restaurant_name"],
                    items=["Chef's pick"],
                    est_total=25.0,
                    cuisine_tags=list(c.get("categories", [])),
                    why_this_one="Nearest open option",
                )
                for i, c in enumerate(candidates[:3])
            ]
            axis = ChoiceAxis.CUISINE
            axis_reason = f"LLM choice-set design failed ({type(e).__name__}) — fell back to default cuisine axis"
            why_these = "Closest open places to your hotel."

        opts = []
        for o in options:
            o.est_delivery_at = deliver_at
            opts.append(_option_dict(o))
        return {
            "choice_payload": {
                "axis": axis.value,
                "axis_reason": axis_reason,
                "why_these": why_these,
                "room_arrival": t["room_arrival"],
                "curation_note": state.get("curation_note"),
                "options": opts,
            }
        }

    def _surface(self, state: GraphState) -> dict:
        """The choice moment. Deterministic by construction (replay-safe)."""
        payload = dict(state["choice_payload"])
        options = list(payload["options"])
        notes: list[str] = []
        while True:
            payload["options"] = options
            payload["notes"] = list(notes)
            answer = interrupt(payload)
            kind = (answer or {}).get("type")
            if kind == "pick":
                return {
                    "picked_option_id": answer["option_id"],
                    "choice_payload": {**payload, "options": options},
                }
            if kind == "order_rejected":
                rid = answer.get("restaurant_id") or (
                    options[0]["restaurant_id"] if options else None
                )
                options = [o for o in options if o["restaurant_id"] != rid]
                shown = {o["restaurant_id"] for o in options}
                pool = [
                    c for c in state.get("candidates", [])
                    if c["restaurant_id"] not in shown and c["restaurant_id"] != rid
                ]
                repl = recover_from_rejection({"restaurant_id": rid}, pool)
                if repl is not None:
                    options.append({
                        "option_id": f"opt-r{len(notes) + 1}",
                        "restaurant_id": repl["restaurant_id"],
                        "restaurant_name": repl["restaurant_name"],
                        "items": ["Popular pick"],
                        "est_total": 25.0,
                        "est_delivery_at": options[0]["est_delivery_at"] if options else None,
                        "cuisine_tags": list(repl.get("categories", [])),
                        "why_this_one": "Backup — your earlier option went offline.",
                    })
                    notes.append(
                        f"a restaurant went offline — recovered with {repl['restaurant_name']}"
                    )
                else:
                    notes.append(
                        "a restaurant went offline — no in-envelope replacement available"
                    )
                continue
            notes.append(f"noted {kind or 'event'} — still waiting for your pick")

    def _place(self, state: GraphState) -> dict:
        picked_id = state["picked_option_id"]
        options = state["choice_payload"]["options"]
        picked = next(o for o in options if o["option_id"] == picked_id)
        order = orders_mod.place_order(picked)
        return {
            "order": order,
            "decision": {
                "action": "placed",
                "reasoning": (
                    f"order placed at {picked['restaurant_name']} — "
                    f"ETA {picked.get('est_delivery_at')}"
                ),
                "picked_option_id": picked_id,
            },
        }

    # --- ArrivalAgent contract -----------------------------------------------

    def handle_event(self, event: TripEvent) -> AgentDecision:
        if self._awaiting_pick:
            if event.type == EventType.USER_PICK:
                resume = {"type": "pick", "option_id": event.parsed().option_id}
            elif event.type == EventType.ORDER_REJECTED:
                p = event.parsed()
                resume = {
                    "type": "order_rejected",
                    "restaurant_id": getattr(p, "rejected_restaurant_id", None),
                }
            else:
                resume = {"type": event.type.value}
            result = self._graph.invoke(Command(resume=resume), self._config)
        else:
            # mode="json": the checkpointer wants plain JSON types in state
            # (enum members and datetimes trip its serializer warnings).
            result = self._graph.invoke(
                {"events": [event.model_dump(mode="json")]}, self._config
            )

        intr = result.get("__interrupt__")
        if intr:
            self._awaiting_pick = True
            payload = intr[0].value if isinstance(intr, (list, tuple)) else intr.value
            return self._surface_decision(payload)

        self._awaiting_pick = False
        return self._terminal_decision(result)

    def _surface_decision(self, payload: dict) -> AgentDecision:
        reasoning_bits = [payload.get("axis_reason") or ""]
        if payload.get("curation_note"):
            reasoning_bits.append(payload["curation_note"])
        reasoning_bits.extend(payload.get("notes") or [])
        return AgentDecision(
            action=Action.SURFACE,
            reasoning="; ".join(b for b in reasoning_bits if b),
            room_arrival_estimate=payload.get("room_arrival"),
            axis=ChoiceAxis(payload["axis"]),
            choice_set=[ChoiceOption(**o) for o in payload["options"]],
            why_these=payload.get("why_these"),
        )

    def _terminal_decision(self, result: dict) -> AgentDecision:
        d = result.get("decision") or {}
        if d.get("action") == "placed":
            return AgentDecision(
                action=Action.PLACED,
                reasoning=d["reasoning"],
                placed_option_id=d["picked_option_id"],
            )
        if d.get("action") == "surface" and d.get("fallback"):
            return AgentDecision(
                action=Action.SURFACE,
                reasoning=d["reasoning"],
                room_arrival_estimate=d.get("room_arrival"),
                axis=None,
                choice_set=[ChoiceOption(**d["fallback"])],
                why_these=d["reasoning"],
            )
        return AgentDecision(
            action=Action.WAIT,
            reasoning=d.get("reasoning", "no decision recorded"),
            room_arrival_estimate=d.get("room_arrival"),
        )

    def state(self) -> dict:
        snap = self._graph.get_state(self._config)
        return dict(snap.values) if snap and snap.values else {}
