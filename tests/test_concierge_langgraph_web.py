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
