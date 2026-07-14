"""The LIVE web demo runs on LangGraph — prove it, and prove the durability.

The web concierge drives each moment through `concierge_graph.graph`, a compiled
StateGraph with a SQLite checkpointer. These tests use deterministic segments
(no network) to show:

  1. a paused moment survives a "process restart" — a BRAND NEW graph +
     checkpointer on the same db file resumes the pause from disk;
  2. an auto-notify moment completes with no interrupt (the agent acts, the graph
     just runs to Done).
"""

from __future__ import annotations

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from arrival_agent.web import concierge_graph as cg


def _graph(db_path: str):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return cg.build_graph(SqliteSaver(conn)), conn


def test_paused_moment_survives_a_restart(tmp_path):
    db = str(tmp_path / "cp.sqlite")
    cfg = {"configurable": {"thread_id": "priya:0"}}   # priya seg 0 = departure heads-up

    # process 1: drive to the pause, then "die" (close the connection)
    g1, c1 = _graph(db)
    r = g1.invoke({"mode": "priya", "seg": 0}, cfg)
    assert r["__interrupt__"][0].value["kind"] == "snooze"
    c1.close()

    # process 2: a fresh graph + checkpointer on the SAME db resumes from disk
    g2, c2 = _graph(db)
    r2 = g2.invoke(cg.Command(resume={"decision": "snooze"}), cfg)
    assert r2["outcomes"][-1]["outcome"] == "acknowledged"
    c2.close()


def test_auto_notify_moment_runs_to_done_without_a_pause(tmp_path):
    db = str(tmp_path / "cp.sqlite")
    g, c = _graph(db)
    # priya seg 1 = the delay hotel notify, which is action-first (auto) → no pause
    r = g.invoke({"mode": "priya", "seg": 1}, {"configurable": {"thread_id": "priya:1"}})
    assert "__interrupt__" not in r
    assert r["outcomes"][-1]["outcome"]["sent"] is True
    c.close()


# --- reconnect after a restart: replay the log, resume the paused moment --------

import asyncio  # noqa: E402

from arrival_agent.web import concierge  # noqa: E402

# fixed restaurants so the dinner moment is deterministic + network-free
_FIXED = [
    {"restaurant_id": "t1", "restaurant_name": "Ramen House", "categories": ["Ramen Restaurant"], "distance_m": 200},
    {"restaurant_id": "t2", "restaurant_name": "Taco Spot", "categories": ["Mexican Restaurant"], "distance_m": 300},
    {"restaurant_id": "t3", "restaurant_name": "Burg", "categories": ["Burger Joint"], "distance_m": 400},
]


def _answer(pause: dict) -> dict:
    k = pause["kind"]
    if k == "pick":
        return {"decision": "pick", "option_id": pause["payload"]["options"][0]["option_id"]}
    return {"snooze": {"decision": "snooze"}, "confirm_dish": {"decision": "confirm"},
            "ask_hotel": {"decision": "no"}}.get(k, {"decision": "decline"})


async def _drive_until(run, stop_at):
    """Drive `run`, answering each pause, until a `stop_at` pause (left unanswered)
    or the stream closes. Returns (task, event kinds seen, closed?)."""
    run.queue = asyncio.Queue()
    task = asyncio.create_task(concierge.drive(run))
    kinds = []
    while True:
        kind, payload = await run.queue.get()
        if kind is concierge._CLOSE:
            return task, kinds, True
        kinds.append(kind)
        if kind == "todo":
            if payload["kind"] == stop_at:
                return task, kinds, False
            aid = payload["action_id"]
            for _ in range(4000):   # wait until the driver is awaiting THIS pause
                cur = run.current
                if run.awaiting and isinstance(cur, dict) and cur.get("action_id") == aid \
                        and run.response and not run.response.done():
                    concierge.registry.submit(run.run_id, _answer(payload))
                    break
                await asyncio.sleep(0)


async def _scenario():
    concierge._GEO_MEMO[concierge._loc("priya")["hotel_address"]] = list(_FIXED)

    # run part-way, then stop at the dinner pick WITHOUT answering it
    run1 = concierge.registry.create("priya")
    task1, _, closed = await _drive_until(run1, stop_at="pick")
    assert not closed, "expected to reach the dinner pick"

    # simulate a crash: cancel the driver and forget the run in memory
    task1.cancel()
    try:
        await task1
    except asyncio.CancelledError:
        pass
    concierge.registry.discard(run1.run_id)
    assert concierge.registry.get(run1.run_id) is None

    # RESTART: reattach from persisted metadata, resume to completion
    run2 = concierge.registry.reattach(run1.run_id)
    assert run2 is not None and run2.resume
    task2, kinds2, _ = await _drive_until(run2, stop_at=None)
    await task2
    return kinds2


def test_reconnect_after_restart_replays_and_resumes():
    kinds = asyncio.run(_scenario())
    assert "context" in kinds        # the thread head was replayed from the log
    assert kinds.count("todo") >= 1  # the paused pick was resumed and answered
    assert kinds[-1] == "done"       # the trip ran to completion after the restart
