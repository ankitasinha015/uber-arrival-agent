"""Tests for the Chroma-backed taste store.

Integration-flavored: real embeddings, real Chroma. Mocking the embeddings
would test nothing — the embedding behavior IS the value of this module.

One session-scoped in-memory store is shared across tests; each test owns a
unique user_id so collections never collide. This shape works around a
Chroma+torch Windows instability where multiple Client instances in one
process crash pytest.

First test run downloads the ~80MB embedding model (cached afterward).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arrival_agent.core.domain.taste import TasteStore
from arrival_agent.core.events import load_scenario


@pytest.fixture(scope="session")
def store():
    """One in-memory Chroma client for the whole test session."""
    return TasteStore(in_memory=True)


_uid_seq = iter(f"u{i}" for i in range(10_000))


@pytest.fixture
def user_id():
    """Unique user_id per test, so collections never collide."""
    return next(_uid_seq)


# --- cold start ---------------------------------------------------------------


def test_cold_start_has_no_history(store, user_id):
    assert not store.has_history(user_id)


def test_cold_start_recent_picks_is_empty(store, user_id):
    assert store.recent_picks(user_id, k=5) == []


def test_cold_start_rank_returns_candidates_unchanged(store, user_id):
    candidates = [
        {"restaurant_id": "r1", "restaurant_name": "A", "categories": ["Thai"]},
        {"restaurant_id": "r2", "restaurant_name": "B", "categories": ["Pizza"]},
    ]
    out = store.rank_candidates(user_id, candidates)
    assert [c["restaurant_id"] for c in out] == ["r1", "r2"]


# --- write + read roundtrip ---------------------------------------------------


def test_record_then_has_history(store, user_id):
    store.record_pick(user_id, {
        "restaurant_name": "Lers Ros",
        "cuisine_tags": ["Thai", "Noodles"],
        "items_ordered": ["boat noodle soup"],
        "rating": 5,
        "city": "SF",
        "timestamp": "2025-12-04T23:40:00-08:00",
    })
    assert store.has_history(user_id)


def test_recent_picks_returns_newest_first(store, user_id):
    store.record_picks(user_id, [
        {"restaurant_name": "Older", "cuisine_tags": ["x"], "rating": 5,
         "timestamp": "2025-01-01T12:00:00+00:00"},
        {"restaurant_name": "Newer", "cuisine_tags": ["y"], "rating": 5,
         "timestamp": "2025-12-01T12:00:00+00:00"},
    ])
    recent = store.recent_picks(user_id, k=2)
    assert recent[0]["restaurant_name"] == "Newer"
    assert recent[1]["restaurant_name"] == "Older"


def test_record_is_idempotent(store, user_id):
    """Re-seeding the same picks shouldn't double-count them."""
    pick = {"restaurant_name": "X", "cuisine_tags": ["a"], "rating": 5,
            "timestamp": "2025-01-01T00:00:00+00:00"}
    store.record_pick(user_id, pick)
    store.record_pick(user_id, pick)
    assert len(store.recent_picks(user_id, k=10)) == 1


# --- the real-value test: ranking changes based on history --------------------


def _candidates_brothy_vs_stirfry():
    return [
        {"restaurant_id": "stir", "restaurant_name": "Bamboo Wok",
         "categories": ["Chinese Restaurant", "Stir-Fry"]},
        {"restaurant_id": "broth", "restaurant_name": "Mensho",
         "categories": ["Japanese Restaurant", "Ramen", "Noodle Soup"]},
        {"restaurant_id": "pizza", "restaurant_name": "Tony Pizza",
         "categories": ["Pizza Place", "Italian Restaurant"]},
    ]


def test_rank_promotes_brothy_when_user_loves_brothy(store, user_id):
    """Seed only brothy/noodle-soup well-rated picks; a brothy candidate
    should rise above stir-fry and pizza."""
    store.record_picks(user_id, [
        {"restaurant_name": "Lers Ros Thai",
         "cuisine_tags": ["Thai", "Noodles", "Soup"],
         "items_ordered": ["boat noodle soup", "khao soi"],
         "rating": 5, "timestamp": "2025-12-04T00:00:00+00:00"},
        {"restaurant_name": "Pho 84",
         "cuisine_tags": ["Vietnamese", "Soup", "Noodles"],
         "items_ordered": ["pho ga"],
         "rating": 5, "timestamp": "2025-10-30T00:00:00+00:00"},
    ])
    ranked = store.rank_candidates(user_id, _candidates_brothy_vs_stirfry())
    ids = [c["restaurant_id"] for c in ranked]
    assert ids[0] == "broth", f"expected brothy first, got {ids}"


def test_rank_ignores_low_rated_picks(store, user_id):
    """A pick rated 2/5 should NOT promote similar candidates."""
    store.record_picks(user_id, [
        {"restaurant_name": "Bad Stirfry Place",
         "cuisine_tags": ["Chinese", "Stir-Fry"],
         "rating": 2, "timestamp": "2025-08-01T00:00:00+00:00"},
        {"restaurant_name": "Lers Ros", "cuisine_tags": ["Thai", "Soup"],
         "rating": 5, "timestamp": "2025-12-04T00:00:00+00:00"},
    ])
    ranked = store.rank_candidates(user_id, _candidates_brothy_vs_stirfry())
    ids = [c["restaurant_id"] for c in ranked]
    assert ids[0] == "broth"
    assert ids.index("stir") > ids.index("broth")


# --- scenario seeding integration --------------------------------------------


def test_seed_from_scenario_writes_all_past_picks(store):
    """Uses the scenario's hardcoded user_id 'ankit_traveler'."""
    scenario_path = Path(__file__).resolve().parents[1] / "scenarios" / "repeat-traveler.json"
    sc = load_scenario(scenario_path)
    written_uid = store.seed_from_scenario(sc)
    assert written_uid == "ankit_traveler"
    recent = store.recent_picks(written_uid, k=20)
    assert len(recent) == len(sc.itinerary["past_picks"])


def test_seed_from_scenario_without_past_picks_returns_none(store):
    """delayed-flight.json carries no past_picks → no-op."""
    scenario_path = Path(__file__).resolve().parents[1] / "scenarios" / "delayed-flight.json"
    sc = load_scenario(scenario_path)
    assert store.seed_from_scenario(sc) is None
