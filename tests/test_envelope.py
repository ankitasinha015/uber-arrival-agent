"""Tests for the curation envelope."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arrival_agent.core.domain.envelope import DelegationEnvelope


PDT = timezone(timedelta(hours=-7))


def _at(h: int) -> datetime:
    return datetime(2026, 5, 20, h, 0, tzinfo=PDT)


# --- should_engage ------------------------------------------------------------


def test_should_engage_true_for_late_arrival():
    env = DelegationEnvelope(after_hour=22)
    assert env.should_engage(_at(23))
    assert env.should_engage(_at(22))


def test_should_engage_true_for_post_midnight_arrival():
    env = DelegationEnvelope(after_hour=22)
    assert env.should_engage(_at(0))   # 00:00
    assert env.should_engage(_at(2))   # 02:00


def test_should_engage_false_for_evening_arrival():
    env = DelegationEnvelope(after_hour=22)
    assert not env.should_engage(_at(18))
    assert not env.should_engage(_at(21))


# --- matches_cuisines / filter_candidates ------------------------------------


def test_filter_keeps_matching_cuisines():
    env = DelegationEnvelope(cuisines=["thai", "indian"])
    candidates = [
        {"restaurant_name": "Lers Ros", "categories": ["Thai Restaurant"]},
        {"restaurant_name": "Pakwan", "categories": ["Indian Restaurant"]},
        {"restaurant_name": "Biergarten", "categories": ["German Restaurant", "Beer Garden"]},
    ]
    out = env.filter_candidates(candidates)
    names = {c["restaurant_name"] for c in out}
    assert names == {"Lers Ros", "Pakwan"}


def test_filter_is_case_insensitive():
    env = DelegationEnvelope(cuisines=["THAI"])
    candidates = [{"restaurant_name": "x", "categories": ["thai bistro"]}]
    assert env.filter_candidates(candidates)


def test_filter_passes_everything_when_no_cuisines():
    env = DelegationEnvelope(cuisines=[])
    candidates = [
        {"restaurant_name": "a", "categories": ["German Restaurant"]},
        {"restaurant_name": "b", "categories": ["Sushi"]},
    ]
    assert len(env.filter_candidates(candidates)) == 2


def test_filter_handles_missing_categories():
    env = DelegationEnvelope(cuisines=["thai"])
    candidates = [{"restaurant_name": "no-tags"}]  # missing categories key
    assert env.filter_candidates(candidates) == []


# --- allows_total -------------------------------------------------------------


def test_allows_total_within_cap():
    env = DelegationEnvelope(max_total=40)
    assert env.allows_total(28)
    assert env.allows_total(40)


def test_allows_total_rejects_over_cap():
    env = DelegationEnvelope(max_total=40)
    assert not env.allows_total(41)


def test_allows_total_passes_unknown():
    env = DelegationEnvelope()
    assert env.allows_total(None)
