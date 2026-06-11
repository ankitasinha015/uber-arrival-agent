"""Tests for the recovery policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arrival_agent.core.domain.recovery import no_supply_fallback, recover_from_rejection


PDT = timezone(timedelta(hours=-7))


def test_recover_returns_next_candidate():
    rejected = {"restaurant_id": "x", "restaurant_name": "Closed Place"}
    remaining = [
        {"restaurant_id": "a", "restaurant_name": "Plan B"},
        {"restaurant_id": "b", "restaurant_name": "Plan C"},
    ]
    out = recover_from_rejection(rejected, remaining)
    assert out is not None and out["restaurant_id"] == "a"


def test_recover_returns_none_when_no_remaining():
    assert recover_from_rejection({"restaurant_id": "x"}, []) is None


def test_no_supply_fallback_schedules_next_morning_breakfast():
    target = datetime(2026, 5, 21, 0, 30, tzinfo=PDT)  # 00:30 arrival
    fb = no_supply_fallback("Marriott Marquis SF", target_room_arrival=target)
    assert fb["kind"] == "breakfast_fallback"
    assert fb["hotel"] == "Marriott Marquis SF"
    assert fb["deliver_at"].date() == (target + timedelta(days=1)).date()
    assert fb["deliver_at"].hour == 7
    assert "breakfast" in fb["reason"].lower()


def test_no_supply_fallback_respects_breakfast_hour_override():
    target = datetime(2026, 5, 21, 0, 30, tzinfo=PDT)
    fb = no_supply_fallback("h", target, breakfast_hour=8)
    assert fb["deliver_at"].hour == 8
