"""Domain: curate the ordered to-dos for a trip moment.

The agent's judgment lives here. Given a moment (departure / delay / arrival) and
context, decide WHICH to-dos matter and in what ORDER. Each to-do is a series of
steps with explicit pause points (where the user picks or sends).

    curate_actions(moment, context, *, memory=None) -> ActionList

Today the per-moment to-dos come from templates, then a memory object (optional)
reshapes them — drops what the user always dismisses, floats what they always do.
The seam for an LLM curator is right here: swap `_TEMPLATES[moment]` for a model
call that picks to-dos for *this* itinerary. For three well-scoped moments the
templates are more reliable and equally honest for the demo; the LLM curation is
the scale story.

Pure: no I/O, no network. The to-do's *steps* are descriptors — the controller
(adapter) executes them by calling the real tools (Foursquare, choice_set,
email.send) and pausing at `pause_for` steps. This module only decides the plan.
"""

from __future__ import annotations

from typing import Protocol

from arrival_agent.core.contract import (
    ActionItem,
    ActionKind,
    ActionList,
    ActionStep,
    Moment,
)


class ActionMemory(Protocol):
    """Behaviour memory the curator may consult. Optional — `curate_actions`
    works without it. Phase 4 implements a concrete store; tests pass a fake."""

    def shape_actions(self, moment: Moment, items: list[ActionItem]) -> list[ActionItem]:
        """Reorder / drop to-dos based on what the user has done before."""
        ...


# --- to-do templates (one builder per kind) -----------------------------------
#
# Each builder returns a fresh ActionItem with its series of steps. The pause
# points are the user's final calls; everything else the agent runs itself.


def _heads_up_leave_earlier() -> ActionItem:
    return ActionItem(
        action_id="leave-earlier",
        kind=ActionKind.HEADS_UP,
        title="Leave 30 min earlier",
        detail="Security lines are heavy right now — it's peak travel season.",
        steps=[
            ActionStep(name="check security wait"),
            ActionStep(name="acknowledge", pause_for="snooze"),
        ],
    )


def _notify_hotel() -> ActionItem:
    return ActionItem(
        action_id="notify-hotel",
        kind=ActionKind.NOTIFY_HOTEL,
        title="Notify hotel",
        detail="Let the front desk know you'll arrive late so they hold the room.",
        steps=[
            ActionStep(name="draft late-arrival note"),
            ActionStep(name="send", pause_for="send"),
            ActionStep(name="confirm sent"),
        ],
    )


def _dinner() -> ActionItem:
    return ActionItem(
        action_id="dinner",
        kind=ActionKind.DINNER,
        title="Dinner near your hotel",
        detail="Timed to land about 20 minutes after you reach your room.",
        steps=[
            ActionStep(name="find what's open near the hotel"),
            ActionStep(name="rank by your taste"),
            ActionStep(name="design 2-3 options"),
            ActionStep(name="pick", pause_for="pick"),
            ActionStep(name="place the order"),
            ActionStep(name="confirm"),
        ],
    )


_TEMPLATES: dict[Moment, list] = {
    Moment.DEPARTURE: [_heads_up_leave_earlier],
    Moment.DELAY: [_notify_hotel],
    Moment.ARRIVAL: [_dinner],
}


def _reasoning(moment: Moment, items: list[ActionItem]) -> str:
    if not items:
        return f"nothing worth surfacing for {moment.value} right now"
    titles = ", ".join(i.title.lower() for i in items)
    return f"at {moment.value}, the things worth handling now: {titles}"


def curate_actions(
    moment: Moment,
    context: dict | None = None,
    *,
    signals: dict | None = None,
    memory: ActionMemory | None = None,
) -> ActionList:
    """Curate the ordered to-dos for `moment`. `signals`, if given, drives the
    intensity dial (how forcefully to respond); `memory` reshapes the list.
    Without signals the dial defaults to HIGH, so existing callers are unchanged.
    """
    from arrival_agent.core.domain.intensity import Intensity, assess, read

    level = assess(moment, signals) if signals is not None else Intensity.HIGH
    the_read = read(moment, signals) if signals is not None else ""

    items = [build() for build in _TEMPLATES.get(moment, [])]
    if level == Intensity.NONE:
        items = []
    if memory is not None:
        items = list(memory.shape_actions(moment, items))
    return ActionList(
        moment=moment, reasoning=_reasoning(moment, items), items=items,
        intensity=level.value, read=the_read,
    )
