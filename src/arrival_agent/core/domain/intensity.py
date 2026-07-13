"""Domain: the intensity dial — how MUCH to act, not just whether.

The agent reads the situation and responds in proportion. Same trip, different
severity, different response:

    HIGH  a full action list — the agent does the work, hands you taps
    LOW   one optional, low-stakes offer — defaults to doing nothing
    NONE  stay quiet — nothing worth surfacing

`assess(moment, signals)` is the dial. It's pure: signals in, an Intensity out.
Adapters pass the mocked/real feeds (delay, arrival hour, live security wait,
minutes-to-flight); the dial decides. This is the thing that makes "the agent
that dumps 4 to-dos on a smooth trip is as broken as the one that stays silent
on a bad one" a rule, not a hope.
"""

from __future__ import annotations

from enum import Enum


class Intensity(str, Enum):
    HIGH = "high"   # full action list
    LOW = "low"     # one optional offer, defaults to nothing
    NONE = "none"   # silent


# Thresholds (named so they're tunable and testable).
LATE_HOUR = 22            # arrivals at/after this (or before dawn) are "late"
DAWN_HOUR = 5
SECURITY_NUDGE_MIN = 30   # below this the line isn't worth a heads-up
SECURITY_URGENT_MIN = 60  # at/above this, leave-now urgency
WINDOW_MIN = (45, 180)    # only nudge about departure inside this pre-flight window
BIG_DELAY_MIN = 20        # a delay of at least this is a real disruption


def _is_late(hour: int | None) -> bool:
    return hour is not None and (hour >= LATE_HOUR or hour < DAWN_HOUR)


def assess(moment, signals: dict | None) -> Intensity:
    """Read the situation for `moment` and return how forcefully to respond.

    signals (all optional): delay_min, arrival_hour, security_wait_min,
    pre_flight_min, security_fresh (bool). Missing signals fail safe toward
    quieter — the agent would rather under-nag than fabricate urgency.
    """
    s = signals or {}
    m = getattr(moment, "value", moment)

    if m == "departure":
        wait = s.get("security_wait_min")
        pre = s.get("pre_flight_min")
        if wait is None or not s.get("security_fresh", True):
            return Intensity.NONE                       # no / stale data -> don't fake it
        if pre is None or not (WINDOW_MIN[0] <= pre <= WINDOW_MIN[1]):
            return Intensity.NONE                       # too early or too late to act
        if wait < SECURITY_NUDGE_MIN:
            return Intensity.NONE                       # short line -> stay quiet
        if wait >= SECURITY_URGENT_MIN:
            return Intensity.HIGH                        # leave now
        return Intensity.LOW                             # moderate -> a gentle heads-up

    # delay / arrival: the food + hotel moments
    late = _is_late(s.get("arrival_hour"))
    delay = s.get("delay_min", 0) or 0
    if late:
        return Intensity.HIGH                            # late arrival -> dinner + hotel matter
    if delay >= BIG_DELAY_MIN:
        return Intensity.HIGH                            # disrupted, even if not late
    return Intensity.LOW                                 # calm/early -> a light optional offer


def read(moment, signals: dict | None) -> str:
    """A one-line, human summary of the signals that drove the dial — this is the
    'how the data travelled' line the UI shows above the response."""
    s = signals or {}
    m = getattr(moment, "value", moment)
    bits = []
    if m == "departure":
        wait = s.get("security_wait_min")
        bits.append(f"security {wait} min" if wait is not None else "no security data")
        if s.get("pre_flight_min") is not None:
            bits.append(f"{s['pre_flight_min']} min to flight")
    else:
        d = s.get("delay_min", 0) or 0
        bits.append(f"delayed {d} min" if d else "on time")
        if s.get("arrival_hour") is not None:
            bits.append(f"arriving {s['arrival_hour']:02d}:00")
    return " · ".join(bits) + f"  →  {assess(moment, signals).value.upper()}"
