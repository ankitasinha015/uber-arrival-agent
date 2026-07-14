"""Durable run metadata + event log for the concierge.

The LangGraph SqliteSaver persists the paused *controller* state, but the browser
also needs to reattach after a server restart: which run existed, what mode it
was, and the exact thread of events already shown. This is that record — a tiny
SQLite store, separate from the checkpointer, holding:

  runs(run_id, mode)          — enough to rebuild the ConciergeRun on reconnect
  events(run_id, seq, ...)    — the SSE event log, replayed to rebuild the thread

On reconnect to a run the in-memory registry has lost (process restarted), the
web layer replays `events_of()` to redraw the conversation, then resumes the
still-paused moment from the LangGraph checkpoint.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

_DB = Path(__file__).resolve().parent / "concierge_runs.sqlite"
_conn = sqlite3.connect(str(_DB), check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, mode TEXT)")
_conn.execute(
    "CREATE TABLE IF NOT EXISTS events "
    "(run_id TEXT, seq INTEGER, kind TEXT, payload TEXT, PRIMARY KEY (run_id, seq))"
)
_conn.commit()
_lock = threading.Lock()


def record_run(run_id: str, mode: str) -> None:
    with _lock:
        _conn.execute("INSERT OR REPLACE INTO runs (run_id, mode) VALUES (?, ?)", (run_id, mode))
        _conn.commit()


def mode_of(run_id: str) -> str | None:
    row = _conn.execute("SELECT mode FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return row[0] if row else None


def append(run_id: str, seq: int, kind: str, payload: dict) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR REPLACE INTO events (run_id, seq, kind, payload) VALUES (?, ?, ?, ?)",
            (run_id, seq, kind, json.dumps(payload)),
        )
        _conn.commit()


def events_of(run_id: str) -> list[tuple[str, dict]]:
    rows = _conn.execute(
        "SELECT kind, payload FROM events WHERE run_id = ? ORDER BY seq", (run_id,)
    ).fetchall()
    return [(kind, json.loads(payload)) for kind, payload in rows]
