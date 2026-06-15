"""Tests for the record/replay cache.

Exercises the wrappers directly against fake modules + a temp cache dir, so no
real network or LLM is touched. Proves: record writes, replay reads without
calling the real function, the API token is stripped from the key (so a replay
with a different token still hits), and a missing entry raises CacheMiss.
"""

from __future__ import annotations

import pytest

from arrival_agent.core import cache
from arrival_agent.core.contract import ChoiceAxis, ChoiceOption
from arrival_agent.core.domain.choice_set import ChoiceSet


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    return tmp_path


# --- http wrapper -------------------------------------------------------------


def test_http_record_then_replay_ignores_token(tmp_cache):
    calls = {"n": 0}

    class Rec:
        @staticmethod
        def get_json(url, *, params=None, headers=None, timeout=10.0):
            calls["n"] += 1
            return {"echo": url, "params": params}

    cache._wrap_http(Rec, "record")
    out = Rec.get_json("http://api/x", params={"access_token": "secret", "q": "hi"})
    assert calls["n"] == 1
    assert out["echo"] == "http://api/x"

    class Rep:
        @staticmethod
        def get_json(*a, **k):
            raise AssertionError("replay must not call the real get_json")

    cache._wrap_http(Rep, "replay")
    # different token, same url + other params -> same key -> cache hit
    out2 = Rep.get_json("http://api/x", params={"access_token": "OTHER", "q": "hi"})
    assert out2["echo"] == "http://api/x"


def test_replay_miss_raises(tmp_cache):
    class Rep:
        @staticmethod
        def get_json(*a, **k):
            raise AssertionError

    cache._wrap_http(Rep, "replay")
    with pytest.raises(cache.CacheMiss):
        Rep.get_json("http://never-recorded", params={})


def test_record_writes_a_file(tmp_cache):
    class Rec:
        @staticmethod
        def get_json(url, *, params=None, headers=None, timeout=10.0):
            return {"ok": True}

    cache._wrap_http(Rec, "record")
    Rec.get_json("http://api/y", params={})
    assert list((tmp_cache / "http").glob("*.json")), "expected a cache file"


# --- choice-set wrapper -------------------------------------------------------


def _sample_choice_set() -> ChoiceSet:
    return ChoiceSet(
        axis=ChoiceAxis.SPEED_VS_QUALITY,
        axis_reason="late and tired",
        options=[
            ChoiceOption(option_id="o1", restaurant_id="r1", restaurant_name="Fast Co",
                         items=["burger"], est_total=16, cuisine_tags=["American"], why_this_one="quick"),
            ChoiceOption(option_id="o2", restaurant_id="r2", restaurant_name="Slow Co",
                         items=["ramen"], est_total=28, cuisine_tags=["Japanese"], why_this_one="worth it"),
        ],
        why_these="pick your energy",
    )


def test_choice_set_record_then_replay(tmp_cache):
    cs = _sample_choice_set()

    class Rec:
        @staticmethod
        def design_choice_set(candidates, trip_context, *, past_picks=None, client=None):
            return cs

    cache._wrap_choice_set(Rec, "record")
    ctx = {"city": "Hotel X", "time_of_day": "00:30", "fatigue": "high"}
    Rec.design_choice_set([], ctx)

    class Rep:
        @staticmethod
        def design_choice_set(*a, **k):
            raise AssertionError("replay must not call the real LLM")

    cache._wrap_choice_set(Rep, "replay")
    # candidates / past_picks differ, but the key is the trip context -> hit
    out = Rep.design_choice_set([{"restaurant_id": "z"}], ctx, past_picks=[{"x": 1}])
    assert isinstance(out, ChoiceSet)
    assert out.axis == ChoiceAxis.SPEED_VS_QUALITY
    assert [o.restaurant_name for o in out.options] == ["Fast Co", "Slow Co"]
    assert out.why_these == "pick your energy"


# --- mode ---------------------------------------------------------------------


def test_mode_defaults_off(monkeypatch):
    monkeypatch.delenv("ARRIVAL_AGENT_CACHE", raising=False)
    assert cache.mode() == "off"


def test_mode_reads_env(monkeypatch):
    monkeypatch.setenv("ARRIVAL_AGENT_CACHE", "replay")
    assert cache.mode() == "replay"
