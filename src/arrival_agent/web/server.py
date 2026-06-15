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

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from arrival_agent.web import runner

app = FastAPI(title="Uber Arrival Agent")


class RunRequest(BaseModel):
    scenario: str = "delayed-flight"


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


@app.post("/api/run/{run_id}/pick")
def submit_pick(run_id: str, req: PickRequest):
    ok = runner.registry.submit_pick(run_id, req.option_id)
    if not ok:
        return JSONResponse({"error": "run not awaiting a pick"}, status_code=409)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    # Step 10 replaces this with the real editorial-restrained frontend.
    return (
        "<!doctype html><meta charset=utf-8>"
        "<title>Uber Arrival Agent</title>"
        "<p style='font-family:system-ui;max-width:40rem;margin:4rem auto'>"
        "Backend is up. The demo frontend lands in step 10. "
        "Try <code>GET /api/scenarios</code>.</p>"
    )
