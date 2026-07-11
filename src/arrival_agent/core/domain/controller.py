"""Domain: the controller loop — present next, run its series, check for next.

This is the runtime the frozen spec describes. Given a curated ActionList for a
moment, the controller walks it:

    start()  -> runs the next to-do's auto steps, stops at its pause (pick/send)
    respond(user_input) -> applies the user's call, runs the post-pause steps,
                           then CHECKS FOR NEXT and advances

It returns either a `Pause` (the loop stopped and needs the user) or `Done` (no
to-dos left). Recovery is not special-cased: a handler can re-pause with a fresh
payload (e.g. a backup restaurant after one goes offline), and the "check for
next" falls out of the same loop.

The controller is pure: it holds no I/O. The actual work of each to-do lives in
a per-kind `Handler` whose `prepare`/`resolve` the adapter wires to the real
tools (Foursquare, choice_set, email.send). Tests inject fake handlers, so the
loop is verified in milliseconds with no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from arrival_agent.core.contract import ActionItem, ActionKind, ActionList


# --- controller results -------------------------------------------------------


@dataclass
class Pause:
    """The loop stopped for the user. `kind` is the pause_for ('pick'/'send'/
    'snooze'); `payload` is what to show (choice set, draft note, heads-up)."""

    action_id: str
    kind: str
    title: str
    payload: dict = field(default_factory=dict)


@dataclass
class Done:
    """The moment finished. `outcomes` is one entry per to-do (done/declined)."""

    outcomes: list[dict] = field(default_factory=list)


# --- what a handler returns ---------------------------------------------------


@dataclass
class Prepared:
    """Result of running a to-do's steps up to its pause. `pause` None means the
    to-do auto-completes with no user input (and `outcome` is its result)."""

    pause: str | None
    payload: dict = field(default_factory=dict)
    outcome: dict | str | None = None


@dataclass
class Resolved:
    """Result of applying the user's input. `done` ends the to-do; `repause`
    (with `payload`) keeps it open with a fresh prompt (e.g. recovery)."""

    done: bool
    outcome: dict | str | None = None
    repause: str | None = None
    payload: dict = field(default_factory=dict)


class Handler(Protocol):
    """Does the real work of one to-do kind. `prepare` runs the auto steps before
    the pause; `resolve` applies the user's call and runs the steps after it."""

    def prepare(self, item: ActionItem, context: dict) -> Prepared: ...

    def resolve(self, item: ActionItem, user_input: dict, context: dict) -> Resolved: ...


# --- the loop -----------------------------------------------------------------

_DECLINE = {"decline", "no", "skip", "cancel"}


class TripController:
    """Walks an ActionList one to-do at a time, pausing for the user's calls."""

    def __init__(
        self,
        actions: ActionList,
        handlers: dict[ActionKind, Handler],
        context: dict | None = None,
    ):
        self.actions = actions
        self.handlers = handlers
        self.context = context or {}
        self._outcomes: list[dict] = []
        self._awaiting: ActionItem | None = None

    @property
    def awaiting(self) -> ActionItem | None:
        return self._awaiting

    def start(self) -> Pause | Done:
        return self._advance()

    def respond(self, user_input: dict) -> Pause | Done:
        item = self._awaiting
        if item is None:
            raise RuntimeError("controller is not awaiting user input")

        decision = (user_input or {}).get("decision")
        if decision in _DECLINE:
            item.status = "declined"
            self._outcomes.append({"action_id": item.action_id, "outcome": "declined"})
            self._awaiting = None
            return self._advance()

        res = self.handlers[item.kind].resolve(item, user_input, self.context)
        if not res.done and res.repause is not None:
            # e.g. a restaurant went offline — same to-do, fresh choice set.
            item.status = "awaiting_user"
            return Pause(item.action_id, res.repause, item.title, res.payload)

        item.status = "done"
        self._outcomes.append({"action_id": item.action_id, "outcome": res.outcome or "done"})
        self._awaiting = None
        return self._advance()

    def _advance(self) -> Pause | Done:
        """Present the next pending to-do; run its auto steps; stop at its pause.
        Auto-completing to-dos loop straight through to the next — that's the
        'check for next after each' behavior."""
        while True:
            item = self.actions.next_pending()
            if item is None:
                return Done(self._outcomes)

            item.status = "running"
            prep = self.handlers[item.kind].prepare(item, self.context)
            if prep.pause is None:
                item.status = "done"
                self._outcomes.append(
                    {"action_id": item.action_id, "outcome": prep.outcome or "done"}
                )
                continue

            item.status = "awaiting_user"
            self._awaiting = item
            return Pause(item.action_id, prep.pause, item.title, prep.payload)
