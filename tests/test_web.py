"""Hermetic tests for the web layer.

The driver (`runner.drive`) is exercised end-to-end with all I/O stubbed — what
runs for real is the SSE-message sequencing and the park-for-pick coordination.
The endpoints are smoke-tested with FastAPI's TestClient for the non-streaming
paths (the SSE stream itself is covered by the driver test).
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from arrival_agent.core.contract import ChoiceAxis, ChoiceOption
from arrival_agent.core.domain import choice_set as choice_set_mod
from arrival_agent.core.domain.choice_set import ChoiceSet
from arrival_agent.core.tools import eta as eta_mod
from arrival_agent.core.tools import restaurants as restaurants_mod
from arrival_agent.web import runner
from arrival_agent.web.server import app


FAKE_CANDIDATES = [
    {"restaurant_id": "r1", "restaurant_name": "Lers Ros",
     "categories": ["Thai Restaurant"], "distance_m": 320},
    {"restaurant_id": "r2", "restaurant_name": "Pakwan",
     "categories": ["Indian Restaurant"], "distance_m": 480},
    {"restaurant_id": "r3", "restaurant_name": "Osha",
     "categories": ["Thai Restaurant"], "distance_m": 520},
]


def _fake_design(candidates, trip_context, *, past_picks=None, client=None):
    options = [
        ChoiceOption(
            option_id=f"opt-{i + 1}",
            restaurant_id=c["restaurant_id"],
            restaurant_name=c["restaurant_name"],
            items=["House special"],
            est_total=20.0 + i,
            cuisine_tags=list(c.get("categories", [])),
            why_this_one=f"stub {i + 1}",
        )
        for i, c in enumerate(candidates[:3])
    ]
    return ChoiceSet(
        axis=ChoiceAxis.CUISINE, axis_reason="stub axis",
        options=options, why_these="stub set",
    )


@pytest.fixture
def stub_tools(monkeypatch):
    monkeypatch.setattr(eta_mod, "estimate_eta", lambda o, d: 16)
    monkeypatch.setattr(
        restaurants_mod, "get_eats_options",
        lambda near, limit=10, **kw: list(FAKE_CANDIDATES),
    )
    monkeypatch.setattr(choice_set_mod, "design_choice_set", _fake_design)


# --- driver end-to-end --------------------------------------------------------


def test_drive_streams_to_placed(stub_tools):
    async def run_it():
        run = runner.registry.create("delayed-flight")
        run.queue = asyncio.Queue()
        task = asyncio.create_task(runner.drive(run))
        messages = []
        while True:
            kind, payload = await run.queue.get()
            if kind is runner._CLOSE:
                break
            messages.append((kind, payload))
            if kind == "awaiting_pick":
                runner.registry.submit_pick(run.run_id, payload["options"][0]["option_id"])
        await task
        return messages

    msgs = asyncio.run(run_it())
    kinds = [k for k, _ in msgs]

    assert "awaiting_pick" in kinds
    assert kinds[-1] == "done"
    decisions = [p["decision"] for k, p in msgs if k == "decision"]
    assert decisions[0]["action"] == "wait"          # opens with a WAIT
    assert any(d["action"] == "surface" for d in decisions)
    assert decisions[-1]["action"] == "placed"        # ends placed
    # the done message carries run metrics
    done = next(p for k, p in msgs if k == "done")
    assert "metrics" in done


def test_drive_surfaces_a_choice_set(stub_tools):
    async def run_it():
        run = runner.registry.create("delayed-flight")
        run.queue = asyncio.Queue()
        task = asyncio.create_task(runner.drive(run))
        awaiting = None
        while True:
            kind, payload = await run.queue.get()
            if kind is runner._CLOSE:
                break
            if kind == "awaiting_pick":
                awaiting = payload
                runner.registry.submit_pick(run.run_id, payload["options"][0]["option_id"])
        await task
        return awaiting

    awaiting = asyncio.run(run_it())
    assert awaiting is not None
    assert 2 <= len(awaiting["options"]) <= 3
    assert awaiting["axis"] == "cuisine"


# --- endpoints ----------------------------------------------------------------


def test_list_scenarios():
    client = TestClient(app)
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()}
    assert "delayed-flight" in names


def test_create_run_returns_id():
    client = TestClient(app)
    r = client.post("/api/run", json={"scenario": "delayed-flight"})
    assert r.status_code == 200
    assert len(r.json()["run_id"]) == 12


def test_create_run_unknown_scenario_404():
    client = TestClient(app)
    r = client.post("/api/run", json={"scenario": "does-not-exist"})
    assert r.status_code == 404


def test_pick_on_unknown_run_409():
    client = TestClient(app)
    r = client.post("/api/run/deadbeef/pick", json={"option_id": "opt-1"})
    assert r.status_code == 409


def test_index_serves_html():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Arrival Agent" in r.text
