"""LangGraph orchestration for the LIVE concierge demo.

The running web app drives each moment of a trip through this compiled
``StateGraph`` with a **SQLite checkpointer**, so a paused trip is durable: the
pause (waiting for the user's pick/send) is persisted to disk keyed by
``thread_id = "{run_id}:{seg}"`` and survives a process restart. Resuming reads
the checkpoint and replays the answers — the same durability the primary
ArrivalAgent LangGraph adapter relies on, now under the demo you actually click.

One node, ``run_segment``, rebuilds that moment's ``TripController`` and loops on
a native ``interrupt()`` at each pause (pick / send / confirm_dish / snooze). The
web layer (``concierge.drive``) invokes the graph, streams each interrupt to the
browser over SSE, and resumes with ``Command(resume=user_input)``.

Replay-safety: on resume LangGraph re-runs the node from the top, replaying prior
interrupt answers in order. The node rebuilds the controller deterministically
(``_segments`` is a pure function of ``mode``) and the live restaurant lookup is
memoized per hotel (see ``concierge._arrival_find``), so the choice set is
identical across replays and the replayed pick still resolves.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from arrival_agent.core.domain.controller import Pause, TripController
from arrival_agent.core.domain.memory import seed_seasoned

__all__ = ["graph", "build_graph", "Command", "pause_payload", "DB_PATH"]


class SegState(TypedDict, total=False):
    """Per-moment graph state. Only ``mode`` + ``seg`` are inputs; the node
    rebuilds everything else deterministically, so the state stays JSON-small and
    the checkpoint is cheap."""

    mode: str
    seg: int
    outcomes: list


def pause_payload(step: Pause) -> dict:
    return {"action_id": step.action_id, "kind": step.kind,
            "title": step.title, "payload": step.payload}


def run_segment(state: SegState) -> dict:
    # Imported here (not at module top) so this module can be imported without a
    # circular dependency on concierge, which imports it lazily in drive().
    from arrival_agent.web import concierge as C

    mode = state["mode"]
    seg = state["seg"]
    memory = seed_seasoned() if C._is_seasoned(mode) else None
    _, actions = C._segments(memory, mode)[seg]
    controller = TripController(actions, C._handlers(mode), C._context(mode))
    step = controller.start()
    while isinstance(step, Pause):
        answer = interrupt(pause_payload(step))   # pause, persist, resume on the pick
        step = controller.respond(answer)
    return {"outcomes": step.outcomes}


def build_graph(checkpointer):
    """Compile the one-node segment graph against a given checkpointer. Tests
    build with a throwaway SqliteSaver; the app uses the disk one below."""
    g = StateGraph(SegState)
    g.add_node("run", run_segment)
    g.add_edge(START, "run")
    g.add_edge("run", END)
    return g.compile(checkpointer=checkpointer)


# Disk-backed checkpointer: the paused trip survives a process restart. One
# connection, shared across the asyncio worker threads (check_same_thread=False).
DB_PATH = Path(__file__).resolve().parent / "concierge_checkpoints.sqlite"
_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
graph = build_graph(SqliteSaver(_conn))
