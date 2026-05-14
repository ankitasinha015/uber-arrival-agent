"""Tool: get_flight_status — MOCKED.

Flight status APIs are flaky and rate-limited, and a demo needs deterministic,
controllable events. This tool reads from a scenario timeline (scenarios/*.json)
instead of a live API, so the delayed-flight demo is reproducible.

Implementation: TODO.
"""

from __future__ import annotations


def get_flight_status(flight_no: str) -> dict:
    """Return current flight status from the active scenario timeline.

    Returns (shape TODO): status, scheduled_arrival, estimated_arrival, on_ground.
    """
    raise NotImplementedError
