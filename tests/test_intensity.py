"""V4 — the intensity dial: read severity, respond in proportion."""

from __future__ import annotations

from arrival_agent.core.contract import Moment
from arrival_agent.core.domain.action_set import curate_actions
from arrival_agent.core.domain.intensity import Intensity, assess, read


# --- departure gate ------------------------------------------------------------

def test_short_security_line_stays_silent():
    assert assess(Moment.DEPARTURE, {"security_wait_min": 8, "pre_flight_min": 120}) is Intensity.NONE


def test_moderate_line_in_window_is_a_gentle_nudge():
    assert assess(Moment.DEPARTURE, {"security_wait_min": 45, "pre_flight_min": 120}) is Intensity.LOW


def test_severe_line_is_urgent():
    assert assess(Moment.DEPARTURE, {"security_wait_min": 75, "pre_flight_min": 90}) is Intensity.HIGH


def test_outside_the_window_stays_silent():
    # 6 hours before the flight — too early to nag
    assert assess(Moment.DEPARTURE, {"security_wait_min": 60, "pre_flight_min": 360}) is Intensity.NONE


def test_missing_or_stale_security_data_never_fakes_it():
    assert assess(Moment.DEPARTURE, {"pre_flight_min": 120}) is Intensity.NONE
    assert assess(Moment.DEPARTURE, {"security_wait_min": 60, "pre_flight_min": 120, "security_fresh": False}) is Intensity.NONE


# --- arrival / delay ----------------------------------------------------------

def test_late_arrival_is_high():
    assert assess(Moment.ARRIVAL, {"arrival_hour": 1}) is Intensity.HIGH      # 1 AM
    assert assess(Moment.ARRIVAL, {"arrival_hour": 23}) is Intensity.HIGH     # 11 PM


def test_on_time_early_arrival_is_light_touch():
    assert assess(Moment.ARRIVAL, {"arrival_hour": 19, "delay_min": 0}) is Intensity.LOW


def test_a_real_delay_is_high_even_if_not_late():
    assert assess(Moment.DELAY, {"arrival_hour": 20, "delay_min": 45}) is Intensity.HIGH


# --- the read line ------------------------------------------------------------

def test_read_shows_the_signals_and_the_verdict():
    r = read(Moment.DEPARTURE, {"security_wait_min": 8, "pre_flight_min": 120})
    assert "security 8 min" in r and "NONE" in r


# --- curate_actions honors the dial -------------------------------------------

def test_curate_none_yields_an_empty_list():
    al = curate_actions(Moment.DEPARTURE, signals={"security_wait_min": 8, "pre_flight_min": 120})
    assert al.intensity == "none" and al.items == []
    assert al.read  # the read line is populated


def test_curate_high_keeps_the_todo():
    al = curate_actions(Moment.DEPARTURE, signals={"security_wait_min": 75, "pre_flight_min": 90})
    assert al.intensity == "high" and len(al.items) == 1


def test_curate_without_signals_defaults_high_unchanged():
    al = curate_actions(Moment.ARRIVAL)   # existing callers pass no signals
    assert al.intensity == "high" and len(al.items) == 1 and al.read == ""
