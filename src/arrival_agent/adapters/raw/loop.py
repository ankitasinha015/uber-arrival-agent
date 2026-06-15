"""Raw adapter — the CONTRAST implementation.

Same agent, same core reasoning (retiming, envelope, recovery, choice-set
design, taste), no orchestration framework. A hand-rolled state machine with
explicit flags where LangGraph gave us a graph, a checkpointer, and a native
interrupt for free.

What hand-rolling costs, made concrete (this is the interview point):
  - State persistence: LangGraph's checkpointer carries accumulated events +
    prediction across invocations on a thread. Here it's just instance
    attributes (`self._events`, `self._await`) — fine in one process, but it
    would NOT survive a restart the way the checkpointed graph would.
  - The interrupt: "surface the choice set, wait for the pick" is a native
    LangGraph pause/resume. Here it's an `_await` flag + a branch at the top of
    handle_event that re-routes events while parked. Re-surfacing on every
    intervening event, recovering on order_rejected — all explicit.
  - Replay-safety: a non-issue here (no checkpointer replays nodes), so unlike
    the LangGraph adapter we hold native ChoiceOption objects instead of
    serializing state to JSON-able dicts.

Given the same scenario and the same (stubbed or cached) choice set, this
produces the SAME terminal decision as the LangGraph adapter — see
tests/test_adapter_contract.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta

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

USER_RESPONSE_BUFFER_MIN = 20.0
DELIVER_AFTER_ARRIVAL_MIN = 20


class RawArrivalAgent(ArrivalAgent):
    """ArrivalAgent backed by a hand-built loop — no framework."""

    def __init__(self, scenario: Scenario, *, taste_store=None, thread_id: str = "run"):
        self._scenario = scenario
        self._envelope = DelegationEnvelope(**scenario.envelope)
        self._hotel = scenario.itinerary.get("hotel", "")
        self._airport = scenario.itinerary.get("airport", "")
        sched = scenario.itinerary.get("scheduled_arrival")
        self._scheduled = datetime.fromisoformat(sched) if isinstance(sched, str) else sched
        self._taste = taste_store
        self._user_id = scenario.itinerary.get("user_id")

        # hand-rolled state (LangGraph would checkpoint this for us)
        self._events: list[TripEvent] = []
        self._ride_eta: int | None = None
        self._await = False
        self._options: list[ChoiceOption] = []
        self._candidates: list[dict] = []
        self._room_arrival: datetime | None = None
        self._axis: ChoiceAxis | None = None
        self._why_these: str | None = None
        self._notes: list[str] = []
        self._reason: str = ""

    # --- ArrivalAgent contract -----------------------------------------------

    def handle_event(self, event: TripEvent) -> AgentDecision:
        if self._await:
            return self._resume(event)
        self._events.append(event)
        return self._step()

    def state(self) -> dict:
        return {
            "events": [e.model_dump(mode="json") for e in self._events],
            "ride_eta_min": self._ride_eta,
            "awaiting_pick": self._await,
        }

    # --- the loop ------------------------------------------------------------

    def _step(self) -> AgentDecision:
        now = max(e.at for e in self._events)

        if self._ride_eta is None and any(e.type == EventType.RIDE_STARTED for e in self._events):
            try:
                self._ride_eta = eta_mod.estimate_eta(self._airport, self._hotel)
            except Exception as e:
                self._ride_eta = -1
                self._notes.append(f"live ETA unavailable ({type(e).__name__}) — using default ride time")
        eta = None if (self._ride_eta is None or self._ride_eta < 0) else self._ride_eta

        timing = decide_timing(
            self._events,
            now=now,
            scheduled_flight_arrival=self._scheduled,
            current_ride_eta_min=eta,
            deliver_after_arrival_min=DELIVER_AFTER_ARRIVAL_MIN,
            user_response_buffer_min=USER_RESPONSE_BUFFER_MIN,
        )
        self._room_arrival = timing.estimate.estimated_at

        if timing.action != "act" or not self._envelope.should_engage(self._room_arrival):
            reason = timing.reason
            if timing.action == "act":
                reason = (
                    f"room arrival {self._room_arrival:%H:%M} is outside the late-night "
                    f"window — staying quiet"
                )
            return AgentDecision(
                action=Action.WAIT, reasoning=reason,
                room_arrival_estimate=self._room_arrival,
            )

        return self._act()

    def _act(self) -> AgentDecision:
        raw = restaurants_mod.get_eats_options(self._hotel, limit=10)
        candidates = self._envelope.filter_candidates(raw)
        if len(candidates) < 2 and raw:
            if self._envelope.cuisines:
                self._notes.append(
                    f"only {len(candidates)} candidate(s) matched your cuisines "
                    f"({', '.join(self._envelope.cuisines)}) — showing nearby alternatives"
                )
            candidates = raw
        if self._taste is not None and self._user_id:
            candidates = self._taste.rank_candidates(self._user_id, candidates)
        self._candidates = candidates

        if not candidates:
            return self._no_supply()

        deliver_at = self._room_arrival + timedelta(minutes=DELIVER_AFTER_ARRIVAL_MIN)
        context = {
            "time_of_day": f"{self._room_arrival:%H:%M} (room arrival estimate)",
            "city": self._hotel,
            "fatigue": "high — late-night arrival after a flight",
        }
        past = (
            self._taste.recent_picks(self._user_id)
            if (self._taste is not None and self._user_id) else None
        )
        try:
            cs = choice_set_mod.design_choice_set(candidates[:8], context, past_picks=past)
            options, self._axis, self._why_these = cs.options, cs.axis, cs.why_these
            axis_reason = cs.axis_reason
        except Exception as e:
            options = [
                ChoiceOption(option_id=f"opt-{i + 1}", restaurant_id=c["restaurant_id"],
                             restaurant_name=c["restaurant_name"], items=["Chef's pick"],
                             est_total=25.0, cuisine_tags=list(c.get("categories", [])),
                             why_this_one="Nearest open option")
                for i, c in enumerate(candidates[:3])
            ]
            self._axis = ChoiceAxis.CUISINE
            self._why_these = "Closest open places to your hotel."
            axis_reason = f"LLM choice-set design failed ({type(e).__name__}) — fell back to default cuisine axis"
        for o in options:
            o.est_delivery_at = deliver_at
        self._options = options
        self._reason = axis_reason
        self._await = True
        return self._surface()

    def _no_supply(self) -> AgentDecision:
        fb = no_supply_fallback(self._hotel, self._room_arrival)
        opt = ChoiceOption(
            option_id="opt-breakfast", restaurant_id="breakfast-fallback",
            restaurant_name="Scheduled breakfast", items=["Breakfast delivery"],
            est_total=0.0, est_delivery_at=fb["deliver_at"], why_this_one=fb["reason"],
        )
        return AgentDecision(
            action=Action.SURFACE, reasoning=fb["reason"],
            room_arrival_estimate=self._room_arrival, axis=None,
            choice_set=[opt], why_these=fb["reason"],
        )

    def _surface(self) -> AgentDecision:
        bits = [self._reason] + self._notes
        return AgentDecision(
            action=Action.SURFACE,
            reasoning="; ".join(b for b in bits if b),
            room_arrival_estimate=self._room_arrival,
            axis=self._axis,
            choice_set=list(self._options),
            why_these=self._why_these,
        )

    # --- the hand-rolled "interrupt" -----------------------------------------

    def _resume(self, event: TripEvent) -> AgentDecision:
        if event.type == EventType.USER_PICK:
            picked_id = event.parsed().option_id
            picked = next(o for o in self._options if o.option_id == picked_id)
            order = orders_mod.place_order(picked.model_dump(mode="json"))
            self._await = False
            return AgentDecision(
                action=Action.PLACED,
                reasoning=f"order placed at {picked.restaurant_name} — ETA {order.get('eta')}",
                placed_option_id=picked_id,
            )

        if event.type == EventType.ORDER_REJECTED:
            rid = getattr(event.parsed(), "rejected_restaurant_id", None) or (
                self._options[0].restaurant_id if self._options else None
            )
            self._options = [o for o in self._options if o.restaurant_id != rid]
            shown = {o.restaurant_id for o in self._options}
            pool = [c for c in self._candidates if c["restaurant_id"] not in shown and c["restaurant_id"] != rid]
            repl = recover_from_rejection({"restaurant_id": rid}, pool)
            if repl is not None:
                self._options.append(ChoiceOption(
                    option_id=f"opt-r{len(self._notes) + 1}",
                    restaurant_id=repl["restaurant_id"], restaurant_name=repl["restaurant_name"],
                    items=["Popular pick"], est_total=25.0,
                    est_delivery_at=self._options[0].est_delivery_at if self._options else None,
                    cuisine_tags=list(repl.get("categories", [])),
                    why_this_one="Backup — your earlier option went offline.",
                ))
                self._notes.append(f"a restaurant went offline — recovered with {repl['restaurant_name']}")
            else:
                self._notes.append("a restaurant went offline — no in-envelope replacement available")
            return self._surface()

        self._notes.append(f"noted {event.type.value} — still waiting for your pick")
        return self._surface()
