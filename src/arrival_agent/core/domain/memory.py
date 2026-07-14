"""Domain: behaviour memory — what the user DOES, so the agent gets sharper.

The taste store (taste.py) remembers what you *like* and ranks dinner options.
This remembers what you *do* with each to-do — send / pick / snooze / decline —
and reshapes the curated list on the next trip:

    memory.shape_actions(moment, items) -> reordered / trimmed items

It drops to-dos the user consistently dismisses (they handle the hotel
themselves, they never want the security nudge) and floats the ones they always
act on. That reshaping is exactly the `ActionMemory` seam `curate_actions`
already calls, so wiring is a one-liner.

Lightweight on purpose: per-user counts (frequency), JSON on disk, no vector DB
and no torch — the frozen spec's "ranking, not model training". `in_memory=True`
for tests and the demo.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from arrival_agent.core.contract import ActionItem, ActionKind, Moment

# Decisions that mean "I engaged" vs "not for me".
_ENGAGED = {"send", "pick", "ack", "confirm"}
_DISMISSED = {"decline", "dismiss", "snooze", "skip"}

_MEMORY_DIR = Path(__file__).resolve().parents[3] / ".memory"

# Drop a to-do kind once the user has dismissed it this many times with no
# engagement. Small so the demo is legible; a real system would tune this.
DROP_THRESHOLD = 2


class ActionMemory:
    """Per-user behaviour memory. Bound to one user so `shape_actions` matches
    the ActionMemory protocol curate_actions expects."""

    def __init__(self, user_id: str, *, in_memory: bool = False):
        self.user_id = user_id
        self._in_memory = in_memory
        # kind -> {"engaged": n, "dismissed": n}
        self._counts: dict[str, dict[str, int]] = defaultdict(lambda: {"engaged": 0, "dismissed": 0})
        if not in_memory:
            self._load()

    # --- recording ---------------------------------------------------------

    def record(self, moment: Moment | str, kind: ActionKind | str, decision: str) -> None:
        """Log what the user did with a to-do. Positive (send/pick) builds
        affinity; dismissive (decline/snooze) erodes it."""
        k = kind.value if isinstance(kind, ActionKind) else kind
        d = (decision or "").lower()
        if d in _ENGAGED:
            self._counts[k]["engaged"] += 1
        elif d in _DISMISSED:
            self._counts[k]["dismissed"] += 1
        if not self._in_memory:
            self._save()

    def _affinity(self, kind: str) -> int:
        c = self._counts.get(kind, {"engaged": 0, "dismissed": 0})
        return c["engaged"] - c["dismissed"]

    def _should_drop(self, kind: str) -> bool:
        c = self._counts.get(kind, {"engaged": 0, "dismissed": 0})
        return c["dismissed"] >= DROP_THRESHOLD and c["engaged"] == 0

    # --- the seam curate_actions calls ------------------------------------

    def shape_actions(self, moment: Moment, items: list[ActionItem]) -> list[ActionItem]:
        """Drop consistently-dismissed to-dos; order the rest by affinity
        (what the user acts on most floats up)."""
        kept = [it for it in items if not self._should_drop(it.kind.value)]
        kept.sort(key=lambda it: self._affinity(it.kind.value), reverse=True)
        return kept

    # --- persistence -------------------------------------------------------

    def _path(self) -> Path:
        return _MEMORY_DIR / f"{self.user_id}.json"

    def _load(self) -> None:
        p = self._path()
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    self._counts[k] = {"engaged": int(v.get("engaged", 0)),
                                       "dismissed": int(v.get("dismissed", 0))}
            except Exception:
                pass  # corrupt file -> start fresh

    def _save(self) -> None:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self._path().write_text(json.dumps(dict(self._counts)), encoding="utf-8")


def seed_seasoned(user_id: str = "seasoned") -> ActionMemory:
    """A returning traveler: over past trips they always handled the hotel
    themselves (declined the notify-hotel to-do) but always ordered dinner.
    So the agent stops surfacing the hotel note and keeps dinner — a shorter,
    sharper list. In-memory, for the demo/tests."""
    m = ActionMemory(user_id, in_memory=True)
    for _ in range(3):
        # He keeps the safety nudge (still worth a glance) but always handles the
        # hotel himself — so only the hotel note gets trimmed, not the whole flow.
        m.record(Moment.DELAY, ActionKind.NOTIFY_HOTEL, "decline")  # handles the hotel themselves
        m.record(Moment.ARRIVAL, ActionKind.DINNER, "pick")         # always orders dinner
    return m
