"""V3 driver parity — the same controller, two orchestrations.

The V3 loop lives in `core/domain/controller.TripController` and is pure: no
framework, no I/O. That means *who drives it* is an orchestration choice, not a
logic one. This module gives the controller two drivers and lets a conformance
test prove they produce the identical pause sequence and outcomes:

  drive_raw        a plain hand-rolled loop (what web/concierge.py does)
  drive_langgraph  a StateGraph whose single node loops on a native interrupt(),
                   with a MemorySaver checkpointer

Both take a `factory` that (re)builds a fresh TripController and a `responder`
that answers each pause. The LangGraph driver rebuilds the controller on every
resume and replays prior answers in order — the same replay-safety the primary
ArrivalAgent LangGraph adapter relies on — so the controller must be
deterministic (it is: stubbed handlers in tests, the replay cache in the demo).

The finding (see docs/framework-comparison.md): raw == LangGraph on behavior.
The framework buys durable trip-state (a real checkpointer would resume the loop
after a process restart mid-trip); it does not change what the agent decides.
"""

from __future__ import annotations

from typing import Callable

from arrival_agent.core.domain.controller import Done, Pause, TripController

# factory() -> a fresh TripController;  responder(pause_dict) -> user_input dict
Factory = Callable[[], TripController]
Responder = Callable[[dict], dict]


def _as_dict(step: Pause) -> dict:
    return {"kind": step.kind, "action_id": step.action_id,
            "title": step.title, "payload": step.payload}


def drive_raw(factory: Factory, responder: Responder) -> tuple[list[str], list[dict]]:
    """Plain loop: start, then respond until Done. Returns (pause kinds, outcomes)."""
    controller = factory()
    step = controller.start()
    pauses: list[str] = []
    while isinstance(step, Pause):
        pauses.append(step.kind)
        step = controller.respond(responder(_as_dict(step)))
    return pauses, step.outcomes


def drive_langgraph(factory: Factory, responder: Responder,
                    *, thread_id: str = "concierge") -> tuple[list[str], list[dict]]:
    """Drive the same controller through a LangGraph StateGraph whose node loops
    on a native interrupt() at each pause, checkpointed by MemorySaver."""
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, interrupt

    def _run(state: dict) -> dict:
        # Fresh controller each node-execution; LangGraph replays prior interrupt
        # answers in order, so a deterministic controller reaches the same state.
        controller = factory()
        step = controller.start()
        while isinstance(step, Pause):
            answer = interrupt(_as_dict(step))
            step = controller.respond(answer)
        return {"outcomes": step.outcomes}

    g = StateGraph(dict)
    g.add_node("run", _run)
    g.add_edge(START, "run")
    g.add_edge("run", END)
    graph = g.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": thread_id}}

    pauses: list[str] = []
    result = graph.invoke({}, config)
    while result.get("__interrupt__"):
        intr = result["__interrupt__"]
        payload = intr[0].value if isinstance(intr, (list, tuple)) else intr.value
        pauses.append(payload["kind"])
        result = graph.invoke(Command(resume=responder(payload)), config)
    return pauses, result["outcomes"]
