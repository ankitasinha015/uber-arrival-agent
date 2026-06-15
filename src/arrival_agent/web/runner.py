"""Run registry + the async driver that streams agent decisions.

One `Run` per browser session. A background task drives the scenario timeline
event-by-event; each decision is pushed onto an asyncio.Queue that the SSE
endpoint drains. When the agent parks at the choice moment (the LangGraph
interrupt) after the last timeline event, the driver awaits a pick Future that
the /pick endpoint resolves — then resumes, places the order, and closes.

The agent's handle_event is synchronous and makes real network + LLM calls, so
it runs in a worker thread (asyncio.to_thread) to avoid blocking the event loop.
The metrics contextvar is copied into the thread per call, so per-run metrics
accumulate correctly and stay isolated between concurrent runs (each driver task
has its own context).

Known limitation: the flight tool keeps the active scenario in a module global,
so two runs streaming *simultaneously* could interleave flight polls. Fine for a
single-user demo; documented rather than solved.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from arrival_agent.adapters.langgraph.graph import LangGraphArrivalAgent
from arrival_agent.core import metrics
from arrival_agent.core.contract import Action, AgentDecision
from arrival_agent.core.events import EventType, Scenario, TripEvent, load_scenario
from arrival_agent.core.tools import flight

SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "scenarios"

# Sentinel pushed onto the queue to tell the SSE generator to close.
_CLOSE = object()


def available_scenarios() -> list[dict]:
    out = []
    for p in sorted(SCENARIOS_DIR.glob("*.json")):
        try:
            sc = load_scenario(p)
            out.append({"name": sc.name, "description": sc.description})
        except Exception:
            continue
    return out


def _serialize_decision(ev: TripEvent, d: AgentDecision) -> dict:
    return {
        "event_type": ev.type.value,
        "event_at": ev.at.isoformat(),
        "decision": d.model_dump(mode="json"),
    }


@dataclass
class Run:
    run_id: str
    scenario: Scenario
    agent: LangGraphArrivalAgent
    # queue + pick are created lazily inside drive(), where a running event loop
    # is guaranteed (constructing them at __init__ time would bind to whatever
    # loop happened to exist, or fail when there is none).
    queue: asyncio.Queue | None = None
    pick: asyncio.Future | None = None
    metrics: metrics.Metrics | None = None
    started: bool = False
    awaiting_pick: bool = False


class RunRegistry:
    """In-memory registry of active runs. Single-process, demo-scale."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def create(self, scenario_name: str) -> Run:
        path = SCENARIOS_DIR / f"{scenario_name}.json"
        if not path.exists():
            raise FileNotFoundError(scenario_name)
        sc = load_scenario(path)

        taste = None
        if sc.itinerary.get("past_picks"):
            from arrival_agent.core.domain.taste import TasteStore
            taste = TasteStore(in_memory=True)
            taste.seed_from_scenario(sc)

        agent = LangGraphArrivalAgent(scenario=sc, taste_store=taste, thread_id=str(uuid4()))
        run = Run(run_id=uuid4().hex[:12], scenario=sc, agent=agent)
        self._runs[run.run_id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def submit_pick(self, run_id: str, option_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None or not run.awaiting_pick or run.pick is None or run.pick.done():
            return False
        run.pick.set_result(option_id)
        return True

    def discard(self, run_id: str) -> None:
        self._runs.pop(run_id, None)


async def drive(run: Run) -> None:
    """Background task: replay the scenario, stream decisions, park for the pick."""
    loop = asyncio.get_running_loop()
    if run.queue is None:
        run.queue = asyncio.Queue()
    run.pick = loop.create_future()
    run.metrics = metrics.start_run()
    flight.set_active_scenario(run.scenario)
    last: AgentDecision | None = None

    try:
        for ev in run.scenario.events:
            flight.advance_clock(ev.at)
            last = await asyncio.to_thread(run.agent.handle_event, ev)
            await run.queue.put(("decision", _serialize_decision(ev, last)))

        # Parked at the choice moment: wait for the user's pick.
        if last is not None and last.action == Action.SURFACE and last.choice_set:
            run.awaiting_pick = True
            await run.queue.put(("awaiting_pick", {
                "options": [o.model_dump(mode="json") for o in last.choice_set],
                "axis": last.axis.value if last.axis else None,
                "why_these": last.why_these,
            }))
            option_id = await run.pick
            run.awaiting_pick = False
            pick_ev = TripEvent(
                type=EventType.USER_PICK,
                at=run.scenario.events[-1].at + timedelta(minutes=2),
                payload={"option_id": option_id},
            )
            placed = await asyncio.to_thread(run.agent.handle_event, pick_ev)
            await run.queue.put(("decision", _serialize_decision(pick_ev, placed)))

        await run.queue.put(("done", {"metrics": run.metrics.as_dict() if run.metrics else {}}))
    except Exception as e:  # surface failures to the client, never hang the stream
        await run.queue.put(("error", {"message": f"{type(e).__name__}: {e}"}))
    finally:
        await run.queue.put((_CLOSE, None))


registry = RunRegistry()
