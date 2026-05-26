"""Tool: get_flight_status — MOCK, scenario-backed.

Flight APIs are flaky and rate-limited, and the demo trip is in the past, so
flight status comes from the active scenario timeline rather than a live API.

Model: FLIGHT_STATUS events are the agent's *wake* triggers; this tool is how the
agent *polls* the current best-known status. The replay layer calls
`set_active_scenario` once, then `advance_clock` as it pushes events. The tool
returns the latest flight status at or before the current clock — exactly what a
real poll against a flight API would return at that moment.

This mirrors a real pattern: a webhook wakes you, then you call the API for the
detail. Here the "API" is the scenario.
"""

from __future__ import annotations

from datetime import datetime

from arrival_agent.core.events import EventType, Scenario
from arrival_agent.core.metrics import instrumented

# Active scenario context, set by the replay layer (cli / web / adapter test).
_active: dict = {"scenario": None, "now": None}


def set_active_scenario(scenario: Scenario, now: datetime | None = None) -> None:
    """Install the scenario the flight mock reads from. `now` is the sim clock;
    None means 'end of timeline' (all events visible)."""
    _active["scenario"] = scenario
    _active["now"] = now


def advance_clock(now: datetime) -> None:
    """Move the sim clock forward. The mock returns flight status <= now."""
    _active["now"] = now


def clear() -> None:
    """Reset the context (used by tests for isolation)."""
    _active["scenario"] = None
    _active["now"] = None


@instrumented("get_flight_status")
def get_flight_status(flight_no: str) -> dict:
    """Latest known flight status at or before the current sim clock.

    Returns: {status, scheduled_arrival, estimated_arrival, actual_arrival,
    flight_no}. Before any flight event fires, returns the scheduled arrival
    from the scenario itinerary with status 'scheduled'.
    """
    scenario: Scenario | None = _active["scenario"]
    if scenario is None:
        raise RuntimeError(
            "no active scenario — call set_active_scenario() before get_flight_status()"
        )
    now: datetime | None = _active["now"]

    latest = None
    for ev in scenario.events:
        if ev.type != EventType.FLIGHT_STATUS:
            continue
        if now is None or ev.at <= now:
            latest = ev

    if latest is None:
        return {
            "status": "scheduled",
            "scheduled_arrival": scenario.itinerary.get("scheduled_arrival"),
            "estimated_arrival": None,
            "actual_arrival": None,
            "flight_no": flight_no,
        }

    p = latest.parsed()
    return {
        "status": p.status,  # type: ignore[attr-defined]
        "scheduled_arrival": scenario.itinerary.get("scheduled_arrival"),
        "estimated_arrival": getattr(p, "estimated_arrival", None),
        "actual_arrival": getattr(p, "actual_arrival", None),
        "flight_no": flight_no,
    }
