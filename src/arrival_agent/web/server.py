"""FastAPI app — streams the agent's decisions to the browser over SSE.

Endpoints:
  GET  /api/scenarios            -> [{name, description}]
  POST /api/run                  -> {run_id}            (body: {scenario})
  GET  /api/run/{id}/stream      -> text/event-stream    (drives the timeline)
  POST /api/run/{id}/pick        -> {ok}                 (body: {option_id})
  GET  /                         -> the demo frontend (step 10; placeholder for now)

The stream is the heart of it: open it and the agent starts reasoning, one
SSE message per decision, parking at the choice set until /pick arrives.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from arrival_agent.core import cache
from arrival_agent.web import concierge, runner

# Activate record/replay before any run. The deployed server sets
# ARRIVAL_AGENT_CACHE=replay, so it serves from scenarios/cache/ with no live
# calls and no API keys.
cache.install()

app = FastAPI(title="Uber Arrival Agent")

_STATIC = Path(__file__).resolve().parent / "static"


class RunRequest(BaseModel):
    scenario: str = "delayed-flight"


class ConsentRequest(BaseModel):
    consent: bool


class PickRequest(BaseModel):
    option_id: str


@app.get("/api/scenarios")
def list_scenarios():
    return runner.available_scenarios()


@app.post("/api/run")
def create_run(req: RunRequest):
    try:
        run = runner.registry.create(req.scenario)
    except FileNotFoundError:
        return JSONResponse({"error": f"unknown scenario: {req.scenario}"}, status_code=404)
    return {"run_id": run.run_id}


def _sse(event_type: str, payload: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


@app.get("/api/run/{run_id}/stream")
async def stream(run_id: str):
    run = runner.registry.get(run_id)
    if run is None:
        return JSONResponse({"error": "unknown run"}, status_code=404)

    async def gen():
        # Create the queue here (on the event loop) before the driver starts, so
        # the drain below can never race ahead of the driver creating it.
        if run.queue is None:
            run.queue = asyncio.Queue()
        # Start the driver on first connect, so the run begins when the client
        # is actually watching.
        if not run.started:
            run.started = True
            asyncio.create_task(runner.drive(run))
        yield _sse("open", {"run_id": run.run_id, "scenario": run.scenario.name})
        while True:
            kind, payload = await run.queue.get()
            if kind is runner._CLOSE:
                break
            yield _sse(kind, payload)
        runner.registry.discard(run.run_id)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/run/{run_id}/consent")
def submit_consent(run_id: str, req: ConsentRequest):
    ok = runner.registry.submit_consent(run_id, req.consent)
    if not ok:
        return JSONResponse({"error": "run not awaiting consent"}, status_code=409)
    return {"ok": True}


@app.post("/api/run/{run_id}/pick")
def submit_pick(run_id: str, req: PickRequest):
    ok = runner.registry.submit_pick(run_id, req.option_id)
    if not ok:
        return JSONResponse({"error": "run not awaiting a pick"}, status_code=409)
    return {"ok": True}


# --- V3 concierge (assistant thread) ----------------------------------------


class RespondRequest(BaseModel):
    decision: str
    option_id: str | None = None
    restaurant_id: str | None = None


@app.post("/api/concierge/run")
def concierge_run():
    run = concierge.registry.create()
    return {"run_id": run.run_id}


@app.get("/api/concierge/{run_id}/stream")
async def concierge_stream(run_id: str):
    run = concierge.registry.get(run_id)
    if run is None:
        return JSONResponse({"error": "unknown run"}, status_code=404)

    async def gen():
        if run.queue is None:
            run.queue = asyncio.Queue()
        if not run.started:
            run.started = True
            asyncio.create_task(concierge.drive(run))
        yield _sse("open", {"run_id": run.run_id})
        while True:
            kind, payload = await run.queue.get()
            if kind is concierge._CLOSE:
                break
            yield _sse(kind, payload)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/concierge/{run_id}/respond")
def concierge_respond(run_id: str, req: RespondRequest):
    ok = concierge.registry.submit(run_id, req.model_dump(exclude_none=True))
    if not ok:
        return JSONResponse({"error": "run not awaiting a response"}, status_code=409)
    return {"ok": True}


@app.get("/concierge", response_class=HTMLResponse)
def concierge_index():
    return (_STATIC / "concierge.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index():
    return (_STATIC / "index.html").read_text(encoding="utf-8")
