# Architecture

How the Uber Arrival Agent is put together. The short version: a **framework-agnostic
core** (pure reasoning + tools, no I/O beyond the tool boundary) with thin **adapters**
that drive it, a **FastAPI + SSE web layer** for the live concierge, and a **ChromaDB**
data layer for synthetic travelers and taste. Restaurant geo is the one live external
call; flight status and order placement are mocked.

## Layers

```
                        ┌──────────────────────── external ─────────────────────────┐
                        │  Foursquare (restaurants+hours) · Mapbox (ETA)  [LIVE]     │
                        │  flight status · order placement                [MOCKED]  │
                        └────────────────────────────────────────────────────────────┘
                                            ▲
                                            │ tool calls
┌───────────────────────────────────────── core (pure, no framework) ──────────────────┐
│  contract.py   the agent-loop contract every adapter implements                        │
│  events.py     trip booked · flight status · ride started/ended · order rejected · pick │
│  tools/        eta · restaurants · flight · orders   (the only I/O boundary)            │
│  domain/       controller · retiming · itinerary · handlers · intensity · memory ·      │
│                envelope · recovery · choice_set · taste     (judgment, no I/O)          │
│  cache.py      record/replay so the CLI demo is free + deterministic                   │
└────────────────────────────────────────────────────────────────────────────────────────┘
        ▲                         ▲                              ▲
        │ drives                  │ drives                       │ reads
┌───────┴────────┐   ┌────────────┴───────────┐    ┌─────────────┴─────────────────────────┐
│  adapters/     │   │  web/ (the concierge)  │    │  data (synthetic, ChromaDB)           │
│  langgraph     │   │  server.py  FastAPI+SSE│    │  travelers   (trip profiles)          │
│  raw           │   │  concierge.py  arrival │    │  eats_orders (Uber Eats history)      │
│  naive         │   │  concierge_graph.py    │    │  classify_cuisine (vector classifier) │
│  compare.py    │   │  runner.py             │    │  runs in Docker; app talks over HTTP  │
└────────────────┘   └────────────────────────┘    └───────────────────────────────────────┘
```

The core never imports a framework. Adapters and the web layer are *consumers* of the
core, not part of it. That is what lets the same agent run on LangGraph, a hand-rolled
loop, and a dumb baseline, and be measured against each other.

## The concierge runtime loop

One agent watches a whole trip. At each **moment** that matters (departure, delay/flight
change, arrival) it curates an ordered list of to-dos, then runs each to-do's series of
steps, pausing only where a human decision is needed. After each step it re-checks what
comes next, so recovery and trip-sync are just "the next action," not special cases.

```
  trigger fires (a trip event)
    │
    ▼
  curate the ordered to-dos for this moment   ── intensity dial scales the list
    │                                             (HIGH / LOW / NONE), memory trims it
    ▼
  ┌─▶ present the NEXT to-do ──────────────────────────────────────────┐
  │     │                                                              │
  │     ▼                                                              │
  │   run its steps:  auto where reversible+free (draft a note)        │
  │                   PAUSE for the calls that matter (send / pick)    │
  │     │                                                              │
  │     ▼                                                              │
  │   on done → CHECK FOR NEXT  (re-assess against current state)      │
  │     │                                                              │
  └─────┘  dependencies (declined dinner → skip order chain),          │
           recovery (restaurant offline → next action = recover),      │
           trip-sync (a delay cascades into every downstream booking)  │
    │                                                                  │
    ▼                                                                  │
  moment complete ◀──────────────────────────────────────────────────┘
```

The "check for next" re-assessment is the load-bearing idea: the agent observes, acts,
and re-evaluates between steps instead of running a fixed script. Implemented as a pure
controller (`core/domain/controller.py`) any adapter can drive.

## The one hard decision: wait vs act

At arrival the agent already has a tight estimate, and still waits. It orders only once
the *room*-arrival estimate is close, so food lands after the traveler is in the room.

```
  flight lands ─▶ retiming: room_arrival = arrival + exit_time + ride_time
                    │
                    ├─ too early?  ──▶ WAIT (do nothing)   ← the judgment
                    │
                    └─ close?      ──▶ curate dinner, surface the choice set

  naive baseline: orders at flight-land (00:32)  →  food waits 40 min at the desk
  this agent:     orders at ~01:12               →  food lands after check-in
```

## Arrival dinner data flow (and its shadow paths)

```
  booking email ─▶ itinerary parse ─▶ live geo ─▶ classify cuisine ─▶ rank by taste ─▶ choice set ─▶ order
  (regex extract)   (flight/airport/    (Foursquare   (vector, 0.65      (cuisine        (2-3 opts,     (mock
                     hotel)              near hotel)    threshold)         frequency)      badge+copy)    place)
        │                │                   │              │                 │               │
        ▼                ▼                   ▼              ▼                 ▼               ▼
   [malformed?      [no airport      [API fails? →    [ambiguous? →     [no in-taste    [restaurant
    → skip field]    code? → skip]    fallback set]    None, shown       match? →        offline? →
                                                       neutrally,        "closest open"  recover: drop
                                                       no false badge]    honest copy]    + backfill]
```

Two of these shadow paths carry the product's honesty guarantee: an ambiguous cuisine
(Korean BBQ, German) returns `None` and is shown by its own category with no taste badge,
and a weak match gets honest "closest open option" copy instead of a false "you order this
most." Both are validated by the eval program (`evals/`).

## Request / SSE sequence (concierge web)

```
  browser                     FastAPI (server.py)              drive() + graph            ChromaDB / Foursquare
    │  POST /api/concierge/run     │                                │                          │
    │─────────────────────────────▶│  create run                    │                          │
    │  GET  …/{id}/stream (SSE)     │                                │                          │
    │─────────────────────────────▶│  start drive() ────────────────▶ curate moment            │
    │                              │                                │  load traveler ──────────▶│
    │  ◀── event: agent / read ────│◀── _emit ──────────────────────│  rank dinner (taste) ────▶│
    │  ◀── event: todo (pause) ────│◀── _emit ──────────────────────│  (pause, await pick)      │
    │  POST …/{id}/respond or /say │                                │                          │
    │─────────────────────────────▶│  resolve pause ────────────────▶ next step                 │
    │  ◀── event: confirm / done ──│◀── _emit ──────────────────────│                          │
```

SSE flushes each beat live. A padding prelude + keepalive + `Cache-Control: no-transform`
keep the stream from being buffered by a proxy (a Cloudflare quick tunnel buffers SSE;
Hugging Face and Render do not).

The web concierge is backed by a LangGraph `StateGraph` with a SqliteSaver checkpointer
(`concierge_graph.py`), so a paused moment survives a process restart. The dinner ranking
itself is deterministic (`concierge._arrival_design`), no LLM call, so the live demo needs
only the Foursquare + Mapbox keys.

## Data layer (ChromaDB, synthetic)

```
  ChromaDB (Docker container, HTTP)
    ├─ collection: travelers     one row per traveler = full trip profile (persona JSON)
    └─ collection: eats_orders   many rows per traveler = synthetic Uber Eats order history
                                    │
              taste ranking ◀──────┘  cuisine-frequency aggregate (most-ordered first)

  cuisine classifier (chroma_store.classify_cuisine)
    restaurant "name — categories"  ─embed(MiniLM)─▶  cosine vs per-cuisine exemplars
                                                        ≥ 0.65 → that cuisine
                                                        <  0.65 → None (honest abstain)
```

Native ChromaDB segfaults on this Windows machine, so it runs in a container and the app
talks to it over HTTP (the Rust core runs in the container; Python only makes network
calls). Embeddings are computed locally from a cached `all-MiniLM-L6-v2` model. Without
`CONCIERGE_CHROMA=1`, the app falls back to an in-code seed with the same data, so tests
and plain imports never need a running container.

## The three adapters + conformance

Same core, three orchestrations, measured side by side (`arrival-agent --compare`):

| Adapter | LOC | LLM calls | Orders |
|---|---|---|---|
| LangGraph (primary) | 344 | 1 | Super Duper Burgers @ 01:12 |
| raw (hand-rolled) | 182 | 1 | Super Duper Burgers @ 01:12 |
| naive (baseline) | 53 | 0 | Ippudo @ **00:32** (40 min early) |

A conformance test proves raw and LangGraph place the *identical* order, so LangGraph's
value isn't fewer lines (it's 2x more) but durable checkpointed state and a native
interrupt the raw loop fakes with flags. Full write-up: [`docs/framework-comparison.md`](docs/framework-comparison.md).

## Deployment

```
  GitHub repo ──push──▶ Hugging Face Space (Docker, port 7860)
                          │  live: uvicorn arrival_agent.web.server:app
                          │  secrets: FOURSQUARE_API_KEY, MAPS_API_KEY
                          ▼
                        public URL, real Foursquare/Mapbox calls per traveler
```

No Anthropic key or ChromaDB is required in the deploy: the persona dinner ranking is
deterministic and the personas come from the in-code seed, so the image stays light. Runbook:
[`docs/DEPLOY_HF.md`](docs/DEPLOY_HF.md).

## Where to read more

- [`DESIGN.md`](DESIGN.md) — the design decisions and the as-built delta.
- [`docs/CASE_STUDY.md`](docs/CASE_STUDY.md) — the product story in one page.
- [`docs/DATA_STORE.md`](docs/DATA_STORE.md) — the ChromaDB store in detail.
- [`docs/PERSONAS.md`](docs/PERSONAS.md) — the five travelers and the trip-sync arc.
- [`evals/README.md`](evals/README.md) — the evaluation program.
