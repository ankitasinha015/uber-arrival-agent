"""Domain: per-kind handlers — the real work behind each to-do.

Each handler implements the controller's `Handler` protocol: `prepare` runs the
to-do's auto steps up to its pause, `resolve` applies the user's call and runs
the steps after it. Dependencies (find restaurants, design the choice set, place
the order, send the email) are injected, so the adapter wires the real tools and
tests inject fakes.

  HeadsUpHandler     leave-earlier nudge; pause = snooze/ack
  NotifyHotelHandler draft a late-arrival note; pause = send
  DinnerHandler      find -> rank -> design; pause = pick; recovery re-pauses
"""

from __future__ import annotations

from typing import Callable

from arrival_agent.core.contract import ActionItem
from arrival_agent.core.domain.controller import Prepared, Resolved


def _opt(o) -> dict:
    """Serialize a ChoiceOption (or dict) to a UI/payload dict."""
    if isinstance(o, dict):
        return o
    d = {
        "option_id": o.option_id,
        "restaurant_id": o.restaurant_id,
        "restaurant_name": o.restaurant_name,
        "items": list(o.items),
        "est_total": o.est_total,
        "cuisine_tags": list(o.cuisine_tags),
        "why_this_one": o.why_this_one,
    }
    if getattr(o, "est_delivery_at", None) is not None:
        d["est_delivery_at"] = (
            o.est_delivery_at.isoformat()
            if hasattr(o.est_delivery_at, "isoformat")
            else o.est_delivery_at
        )
    return d


# --- heads-up (departure) -----------------------------------------------------


class HeadsUpHandler:
    """A nudge the user just acknowledges or snoozes. No downstream work."""

    def prepare(self, item: ActionItem, context: dict) -> Prepared:
        return Prepared(pause="snooze", payload={"detail": item.detail})

    def resolve(self, item: ActionItem, user_input: dict, context: dict) -> Resolved:
        return Resolved(done=True, outcome="acknowledged")


# --- notify hotel (delay) -----------------------------------------------------


def _default_draft(context: dict) -> str:
    when = context.get("arrival_hhmm", "late tonight")
    return (
        f"Guest arriving around {when} on a delayed flight — "
        f"please hold the reservation."
    )


class NotifyHotelHandler:
    """Draft a late-arrival note, pause for the user to send it."""

    def __init__(self, send: Callable[[str], dict], draft: Callable[[dict], str] | None = None):
        self._send = send
        self._draft = draft or _default_draft
        self._note: str | None = None

    def prepare(self, item: ActionItem, context: dict) -> Prepared:
        self._note = self._draft(context)
        return Prepared(pause="send", payload={"draft": self._note})

    def resolve(self, item: ActionItem, user_input: dict, context: dict) -> Resolved:
        result = self._send(self._note or "")
        return Resolved(done=True, outcome={"sent": True, "note": self._note, "result": result})


# --- dinner (arrival) ---------------------------------------------------------


class DinnerHandler:
    """find -> rank -> design the choice set (pause: pick). On 'order_rejected'
    the same to-do re-pauses with a recovered set — that's recovery as a step,
    not a special case."""

    def __init__(
        self,
        find: Callable[[dict], list],
        design: Callable[[list, dict], object],
        place: Callable[[dict], dict],
        recover: Callable[[dict, list], dict | None],
        rank: Callable[[list], list] | None = None,
    ):
        self._find = find
        self._design = design
        self._place = place
        self._recover = recover
        self._rank = rank
        self._candidates: list = []
        self._options: list[dict] = []

    def prepare(self, item: ActionItem, context: dict) -> Prepared:
        candidates = self._find(context)
        if self._rank is not None:
            candidates = self._rank(candidates)
        self._candidates = candidates
        cs = self._design(candidates, context)
        self._options = [_opt(o) for o in cs.options]
        payload = {
            "axis": getattr(cs.axis, "value", cs.axis),
            "why_these": cs.why_these,
            "options": self._options,
        }
        return Prepared(pause="pick", payload=payload)

    def resolve(self, item: ActionItem, user_input: dict, context: dict) -> Resolved:
        decision = (user_input or {}).get("decision")

        if decision in ("order_rejected", "offline"):
            rid = user_input.get("restaurant_id") or (
                self._options[0]["restaurant_id"] if self._options else None
            )
            self._options = [o for o in self._options if o["restaurant_id"] != rid]
            shown = {o["restaurant_id"] for o in self._options}
            pool = [
                c for c in self._candidates
                if c["restaurant_id"] not in shown and c["restaurant_id"] != rid
            ]
            repl = self._recover({"restaurant_id": rid}, pool)
            note = "no in-envelope replacement available"
            if repl is not None:
                self._options.append({
                    "option_id": f"opt-r{len(self._options) + 1}",
                    "restaurant_id": repl["restaurant_id"],
                    "restaurant_name": repl["restaurant_name"],
                    "items": ["Popular pick"],
                    "est_total": 25.0,
                    "cuisine_tags": list(repl.get("categories", [])),
                    "why_this_one": "Backup — your earlier option went offline.",
                })
                note = f"recovered with {repl['restaurant_name']}"
            return Resolved(
                done=False, repause="pick",
                payload={"options": self._options, "note": note},
            )

        option_id = (user_input or {}).get("option_id")
        picked = next((o for o in self._options if o["option_id"] == option_id), None)
        if picked is None:
            # unknown option — keep the pause open rather than crash
            return Resolved(done=False, repause="pick", payload={"options": self._options})
        order = self._place(picked)
        return Resolved(
            done=True,
            outcome={"placed": picked["restaurant_name"], "option_id": option_id, "order": order},
        )
