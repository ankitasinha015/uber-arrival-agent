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
    for extra in ("badge", "dish_pitch"):          # taste-match hints (optional)
        v = getattr(o, extra, None)
        if v:
            d[extra] = v
    return d


# --- heads-up (departure) -----------------------------------------------------


class HeadsUpHandler:
    """A nudge the user just acknowledges or snoozes. No downstream work."""

    def prepare(self, item: ActionItem, context: dict) -> Prepared:
        return Prepared(pause="snooze", payload={"detail": item.detail})

    def resolve(self, item: ActionItem, user_input: dict, context: dict) -> Resolved:
        if (user_input or {}).get("decision") == "refine":  # stray text — don't act
            return Resolved(done=False, repause="snooze",
                            payload={"detail": item.detail, "note": "Tap 'Got it', or say 'skip'."})
        return Resolved(done=True, outcome="acknowledged")


# --- notify hotel (delay) -----------------------------------------------------


def _default_draft(context: dict) -> str:
    when = context.get("arrival_hhmm", "late tonight")
    return (
        f"Hello, I have a reservation arriving later than planned tonight, around "
        f"{when}. Could you please hold my room and note the late arrival so check-in "
        f"is ready when I get there? Thank you very much."
    )


class NotifyHotelHandler:
    """Ask first, then draft-and-send. The traveler decides whether the hotel
    hears about the late arrival at all — only on a yes do we draft the note and
    pause for them to send it. 'no' skips the whole thing."""

    def __init__(self, send: Callable[[str], dict], draft: Callable[[dict], str] | None = None):
        self._send = send
        self._draft = draft or _default_draft
        self._note: str | None = None

    def _ask(self, context: dict, hint: str | None = None) -> Prepared:
        when = context.get("arrival_hhmm", "late tonight")
        payload = {
            "question": f"Your flight's delayed — want me to let the hotel know you'll arrive around {when}?",
            "arrival_hhmm": when,
        }
        if hint:
            payload["note"] = hint
        return Prepared(pause="ask_hotel", payload=payload)

    def prepare(self, item: ActionItem, context: dict) -> Prepared:
        return self._ask(context)

    def resolve(self, item: ActionItem, user_input: dict, context: dict) -> Resolved:
        ui = user_input or {}
        decision = ui.get("decision")

        if self._note is None:                     # still at the ask
            if decision in ("yes", "notify", "send"):
                self._note = self._draft(context)
                return Resolved(done=False, repause="send", payload={"draft": self._note})
            if decision in ("no", "decline", "skip"):
                return Resolved(done=True, outcome={"sent": False, "skipped": True})
            # stray/unknown text at the ask — re-ask with a nudge
            hint = "Tap 'Yes, tell them' to notify the hotel, or 'No' to skip."
            p = self._ask(context, hint)
            return Resolved(done=False, repause="ask_hotel", payload=p.payload)

        # note drafted — now at the send step
        if decision == "refine":                   # stray text — don't send, point at Edit
            return Resolved(done=False, repause="send", payload={
                "draft": self._note,
                "note": "Tap Edit to change the note, Send to send it, or say 'skip'.",
            })
        if decision in ("no", "decline"):          # backed out at the last moment
            return Resolved(done=True, outcome={"sent": False, "skipped": True})
        note = (ui.get("note") or "").strip() or self._note or ""   # honor an edited note
        self._note = note
        result = self._send(note)
        return Resolved(done=True, outcome={"sent": True, "note": note, "result": result})


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
        self._picked: dict | None = None

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
            "lead": getattr(cs, "lead", None),
        }
        return Prepared(pause="pick", payload=payload)

    def _candidate_option(self, c: dict, i: int) -> dict:
        """Turn a raw candidate (no price) into a surfaced option."""
        return {
            "option_id": f"opt-x{i}",
            "restaurant_id": c["restaurant_id"],
            "restaurant_name": c["restaurant_name"],
            "items": ["House pick"],
            "est_total": 19.0 + 3 * i,
            "cuisine_tags": list(c.get("categories", [])),
            "why_this_one": "another open spot near your hotel",
            "est_delivery_at": self._options[0].get("est_delivery_at") if self._options else None,
        }

    def _refine(self, user_input: dict) -> Resolved:
        """The user typed a refinement — re-shape the options and stay at the pick."""
        mode = (user_input or {}).get("mode")
        term = (user_input or {}).get("term")
        opts = list(self._options)

        if mode == "cheaper":
            opts = sorted(opts, key=lambda o: o.get("est_total") or 999)
            note = "sorted by price, cheapest first"
        elif mode == "cuisine" and term:
            t = term.lower()
            def _m(names: list) -> bool:
                return t in " ".join(names).lower()
            kept = [o for o in opts if _m(o.get("cuisine_tags", []) + [o["restaurant_name"]])]
            shown = {o["restaurant_id"] for o in kept}
            extra = [c for c in self._candidates
                     if _m(c.get("categories", []) + [c["restaurant_name"]])
                     and c["restaurant_id"] not in shown]
            for i, c in enumerate(extra[: max(0, 3 - len(kept))]):
                kept.append(self._candidate_option(c, i))
            opts, note = (kept, f"showing {term} spots") if kept else (
                opts, f"nothing open nearby matched '{term}' — here's the set again")
        elif mode == "other":
            shown = {o["restaurant_id"] for o in opts}
            fresh = [c for c in self._candidates if c["restaurant_id"] not in shown][:3]
            opts, note = ([self._candidate_option(c, i) for i, c in enumerate(fresh)],
                          "a different set nearby") if fresh else (
                opts, "that's all that's open near you right now")
        else:
            note = "I can do cheaper, a cuisine (say 'mexican'), or 'something else' — or just tap a card."

        self._options = opts
        return Resolved(done=False, repause="pick", payload={"options": opts, "note": note})

    def resolve(self, item: ActionItem, user_input: dict, context: dict) -> Resolved:
        decision = (user_input or {}).get("decision")

        if decision == "refine":
            return self._refine(user_input)

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

        if decision == "back":                       # back to the restaurant list
            self._picked = None
            return Resolved(done=False, repause="pick", payload={"options": self._options})

        if decision == "confirm":                    # confirm the dish -> order to the room
            picked = self._picked or (self._options[0] if self._options else None)
            if picked is None:
                return Resolved(done=False, repause="pick", payload={"options": self._options})
            dish = (picked.get("items") or ["order"])[0]
            order = self._place(picked)
            return Resolved(done=True, outcome={
                "placed": picked["restaurant_name"], "dish": dish,
                "option_id": picked["option_id"], "order": order,
            })

        # a restaurant pick -> suggest their usual dish there, ask to send it to the room
        option_id = (user_input or {}).get("option_id")
        picked = next((o for o in self._options if o["option_id"] == option_id), None)
        if picked is None:
            return Resolved(done=False, repause="pick", payload={"options": self._options})
        self._picked = picked
        dish = (picked.get("items") or ["a popular dish"])[0]
        hotel = (context.get("city") or "your hotel").split(",")[0]
        return Resolved(done=False, repause="confirm_dish", payload={
            "restaurant_name": picked["restaurant_name"], "dish": dish, "hotel": hotel,
            "pitch": picked.get("dish_pitch"),          # taste-honest sentence (or None)
        })
