"""Record/replay cache for external calls.

The public demo must never burn API quota, must not need secrets on the server,
and should be deterministic (every visitor sees the same polished run). This
module makes that possible.

Modes via the ARRIVAL_AGENT_CACHE env var:
  off     (default) — live calls, no cache. Local dev / tests.
  record  — live calls AND write each response to scenarios/cache/. Run locally
            once (with real keys) to populate the cache, then commit it.
  replay  — read from scenarios/cache/, never call out, no API keys required.
            What the deployed server runs.

What is cached:
  - HTTP (Mapbox geocode + directions, Foursquare search) at the get_json layer,
    keyed on url + params with the API token stripped from the key.
  - The LLM choice-set design, keyed on the trip context. In this demo each
    scenario surfaces exactly one choice set, and (hotel + room-arrival estimate)
    uniquely identifies it, so the context alone is a sufficient, reproducible key.

What is NOT cached — the taste store. It runs locally during *record* (its
ranking + past-pick influence is baked into the recorded choice set) and is
skipped entirely during *replay*. So the deployed image needs no torch /
sentence-transformers, and replay still shows the taste-aware result.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# this file is src/arrival_agent/core/cache.py -> parents[3] is the repo root
CACHE_DIR = Path(__file__).resolve().parents[3] / "scenarios" / "cache"

_SECRET_PARAMS = {"access_token"}
_installed = False


class CacheMiss(RuntimeError):
    """A replay lookup found no recorded response — record the scenario first."""


def mode() -> str:
    return os.environ.get("ARRIVAL_AGENT_CACHE", "off")


def _hash(obj) -> str:
    raw = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _path(kind: str, key: str) -> Path:
    return CACHE_DIR / kind / f"{key}.json"


def _read(kind: str, key: str):
    p = _path(kind, key)
    if not p.exists():
        raise CacheMiss(
            f"{kind}/{key} not recorded — run with ARRIVAL_AGENT_CACHE=record first"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def _write(kind: str, key: str, data) -> None:
    p = _path(kind, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _wrap_http(module, m: str) -> None:
    real = module.get_json

    def wrapped(url, *, params=None, headers=None, timeout=10.0):
        clean = {k: v for k, v in (params or {}).items() if k not in _SECRET_PARAMS}
        key = _hash(["http", url, clean])
        if m == "replay":
            return _read("http", key)
        result = real(url, params=params, headers=headers, timeout=timeout)
        if m == "record":
            _write("http", key, result)
        return result

    module.get_json = wrapped


def _wrap_choice_set(module, m: str) -> None:
    from arrival_agent.core.contract import ChoiceAxis, ChoiceOption
    from arrival_agent.core.domain.choice_set import ChoiceSet

    real = module.design_choice_set

    def to_dict(cs: ChoiceSet) -> dict:
        return {
            "axis": cs.axis.value,
            "axis_reason": cs.axis_reason,
            "why_these": cs.why_these,
            "options": [o.model_dump(mode="json") for o in cs.options],
        }

    def from_dict(d: dict) -> ChoiceSet:
        return ChoiceSet(
            axis=ChoiceAxis(d["axis"]),
            axis_reason=d["axis_reason"],
            options=[ChoiceOption(**o) for o in d["options"]],
            why_these=d["why_these"],
        )

    def wrapped(candidates, trip_context, *, past_picks=None, client=None):
        key = _hash(["choice_set", trip_context])
        if m == "replay":
            return from_dict(_read("choice_set", key))
        result = real(candidates, trip_context, past_picks=past_picks, client=client)
        if m == "record":
            _write("choice_set", key, to_dict(result))
        return result

    module.design_choice_set = wrapped


def install() -> str:
    """Activate the cache for the current mode. Idempotent; returns the mode."""
    global _installed
    m = mode()
    if m == "off" or _installed:
        return m

    if m == "replay":
        # Key getters run before the cached get_json (to build params/headers),
        # so give them non-empty stubs — no real call is ever made in replay.
        from arrival_agent.core import config
        for k in ("MAPS_API_KEY", "FOURSQUARE_API_KEY", "ANTHROPIC_API_KEY"):
            if not os.environ.get(k):
                os.environ[k] = "replay-stub"
        config.mapbox_token.cache_clear()
        config.foursquare_key.cache_clear()
        config.anthropic_key.cache_clear()

    from arrival_agent.core.domain import choice_set
    from arrival_agent.core.tools import eta, restaurants

    _wrap_http(eta, m)
    _wrap_http(restaurants, m)
    _wrap_choice_set(choice_set, m)
    _installed = True
    return m
