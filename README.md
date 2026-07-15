---
title: Uber Arrival Agent
emoji: 🛬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Travel Mode × Eats trip concierge — a live agent demo
---

# Uber Arrival Agent

### An agent that knows when *not* to act.

Most trip apps send a notification. This one decides when to stay quiet. You're flying
somewhere and you'll land late. It watches the trip, predicts when you'll actually be in
your hotel room, and hands you a dinner already timed to arrive after you do.

**The hard part is restraint.** A naive version orders the moment your flight lands and
delivers dinner at **00:32**, 40 minutes before you reach the room. This agent waits until
**01:12**, because ordering early leaves food at the front desk while you're still in the
cab. Picking one restaurant out of fifty is search. Deciding *not* to order yet is judgment.

> **Positioning:** Uber's GO-GET 2026 shipped the rails (Travel Mode, room-service delivery,
> Eats for the Way, a voice assistant). The missing layer is a proactive, stateful agent that
> orchestrates them across a trip when something goes wrong. This is that layer.

**[▶ Try it live](https://ankita015-uber-arrival-agent.hf.space/concierge)** ·
**[Read the 2-minute case study](docs/CASE_STUDY.md)**

## Trip Concierge

The arrival agent above grew into a **trip concierge**: one agent watches the whole
trip and, at each moment that matters, hands you a curated **action list**. Some steps
it runs on its own and just tells you (a flight-change is already re-syncing your
bookings by the time you look); the consequential ones it pauses for. It gets sharper
about you each trip.

Open **`/concierge`** for the assistant-thread demo:

```
departure     → "security lines are heavy — leave earlier"           (tap: got it)
delay/change  → auto-notifies the hotel, then re-syncs every arrival-  (agent acts,
                coupled booking: cab, porter, rental, dinner reservation  tells you)
arrival       → "dinner near your hotel, timed to your room" — most-    (tap: pick,
                ordered dish, ready to send to the room                   then order)
```

Each to-do is a *series of steps* the agent runs itself, pausing only where your call
matters. After each one it **re-checks what's next** — so recovery (a restaurant goes
offline → surface a backup in-thread) and trip-sync (a delay cascades into every
downstream booking) are just the next action, not special cases.

- **It acts in proportion.** An **intensity dial** (HIGH / LOW / NONE) scales the whole
  list to the traveler and the moment — full hand-holding for a nervous first-timer,
  silence for a road warrior. **Behaviour memory** drops what a returning traveler
  always dismisses.
- **Five personas, five cities** — Chicago, New York, LA, San Francisco, and **Berlin
  (international**, with the longer immigration + baggage exit time). Each has a distinct
  signature moment (meet-&-greet, rental, Uber, dinner reservation). See
  [`docs/PERSONAS.md`](docs/PERSONAS.md).

The dinner options and their axis come from one LLM call; the loop itself is a pure,
framework-agnostic controller (`core/domain/controller.py`) any adapter can drive.

The original single-moment arrival agent (below) is now just the *arrival* moment of
this concierge, and still runs at `/`.

### Data: a synthetic first-party store (ChromaDB)

Real trip/user data isn't available, so the demo runs on **synthetic data seeded into
ChromaDB** — the same shape a real backend would have. A `travelers` collection holds
each trip's facts; an `eats_orders` collection holds synthetic **Uber Eats order
history**, and the dinner **taste ranking is derived from it** (aggregate the cuisines
someone orders most) rather than hardcoded — the first-party-data "moat", made
data-driven. The **one** thing that stays a live external call is restaurant geo
(Foursquare). Details in [`docs/DATA_STORE.md`](docs/DATA_STORE.md).

---

## Why it's an agent, not a notification

A notification says *"you might be hungry."* This shows up with a resolved, timed,
supply-checked order. The value is everything *behind* the prompt being already
solved: arrival prediction, supply check, continuous re-timing, and recovery when a
restaurant drops.

The hard part — and the genuinely agentic part — is **knowing when not to act.** When
the ride starts, the agent has a tight arrival estimate but still *waits*, because
ordering then would land food at the front desk while you're in transit. It surfaces
only once the timing is right. And its most agentic single decision isn't picking a
restaurant — it's **designing the choice set**: which *axis* the 2-3 options should
vary along (cuisine vs speed-vs-quality vs familiarity-vs-novelty), chosen for this
user at this moment. Picking one restaurant out of fifty is search. Picking three that
vary along an axis that matters is judgment.

---

## Run it

Locally, against live APIs (needs your own keys):

```bash
cp .env.example .env          # add FOURSQUARE_API_KEY, MAPS_API_KEY (Mapbox), ANTHROPIC_API_KEY
pip install -e ".[taste]"     # core + the taste store (sentence-transformers)
python -m uvicorn arrival_agent.web.server:app --port 8077
# open http://127.0.0.1:8077  (arrival agent)  ·  /concierge  (full trip concierge)
```

The concierge reads travelers + order history from ChromaDB. Start the container and
set `CONCIERGE_CHROMA=1` (it seeds synthetic data on first run); without it, the app
falls back to an in-code seed. See [`docs/DATA_STORE.md`](docs/DATA_STORE.md):

```bash
docker run -d --name chroma -p 8001:8000 chromadb/chroma
CONCIERGE_CHROMA=1 python -m uvicorn arrival_agent.web.server:app --port 8077
```

Or drive a scenario in the terminal and watch every decision:

```bash
python -m arrival_agent.cli --scenario delayed-flight
```

**Record once, replay free forever.** The public demo serves recorded API + LLM
responses — no quota, no keys, deterministic:

```bash
ARRIVAL_AGENT_CACHE=record python -m arrival_agent.cli --scenario delayed-flight   # capture (real keys)
ARRIVAL_AGENT_CACHE=replay python -m arrival_agent.cli --scenario delayed-flight   # replay (no network)
```

**Deploy your own.** The live demo runs on Hugging Face Spaces (free, always-on, makes
real Foursquare/Mapbox calls). Full runbook: [`docs/DEPLOY_HF.md`](docs/DEPLOY_HF.md).
A `fly.toml` is also included if you prefer Fly.io (`fly deploy`).

---

## How it works

A framework-agnostic **core** (the agent's reasoning + tools) with thin **adapters**
that wrap it in an orchestration framework — so the same agent can run on, and be
compared across, different frameworks.

```
src/arrival_agent/
  core/
    contract.py     the agent-loop contract every adapter implements
    events.py       event model: trip booked, flight status, ride started/ended,
                    order rejected, check-in, user pick
    tools/          eta (Mapbox), restaurants (Foursquare), flight + orders (mocked)
    domain/         the reasoning — pure, no I/O:
      controller.py   the concierge loop: run steps, pause only where your call matters
      retiming.py     predict room arrival; the wait-vs-act rule
      itinerary.py    parse the booking email into a trip (flight/airport/hotel regex)
      handlers.py     per-moment steps (heads-up, notify-hotel ask-first, dinner)
      intensity.py    the HIGH/LOW/NONE dial — scale the list to traveler + moment
      memory.py       behaviour memory — drop what a returning traveler dismisses
      envelope.py     the user's one-time curation policy
      recovery.py     restaurant-offline + no-supply fallbacks
      choice_set.py   the single LLM call: pick the axis, design 2-3 options
      taste.py        per-user vector store ranking past picks (cosine, local)
    cache.py        record/replay so the demo is free + deterministic
  adapters/
    langgraph/      primary: StateGraph + checkpointer + a native interrupt at
                    the choice moment
    raw/            contrast: the same agent hand-rolled, no framework
    naive/          baseline: orders too early, no choice-set design (the strawman)
  compare.py        run all three, emit a metrics table (LOC / tokens / timing)
  web/              FastAPI + SSE — the concierge demo:
    concierge.py      arrival design: live geo → cuisine-ranked dinner → dish to room
    chroma_store.py   the synthetic ChromaDB store + confidence-gated cuisine classifier
    concierge_graph.py LangGraph-backed concierge with a SqliteSaver checkpointer
scenarios/          mock event timelines (+ recorded cache/ for replay)
evals/              binary evaluators, LLM-judge validation, RAG + classifier evals
```

The loop, on the LangGraph adapter:

```
  trip event ─▶ predict arrival ─▶ wait?  ─yes─▶ END (persist, sleep till next event)
                                     │no
                                     ▼
                  curate (Foursquare + taste) ─▶ design choice set (LLM)
                                     │
                                     ▼
                    ★ interrupt: surface options, wait for the pick ★
                                     │
                  order_rejected ──▶ recover (drop dead option, backfill) ─┐
                                     │                                       │
                       user picks ──▶ place order ─▶ END        ◀───────────┘
```

LangGraph fits because the trip is **long-running, event-driven, and stateful**, with
a **human in the loop at one specific moment** — "wait for the ride, then re-decide"
is a graph transition, and "surface the choice set and wait for the pick" is a native
interrupt.

The same agent also runs on a hand-rolled loop and a deliberately-dumb baseline, so
they can be measured side by side (`arrival-agent --compare`):

| Adapter | LOC | LLM calls | Ordered |
|---------|-----|-----------|---------|
| LangGraph | 344 | 1 | Super Duper Burgers @ 01:12 |
| raw | 182 | 1 | Super Duper Burgers @ 01:12 |
| naive | 53 | 0 | Ippudo @ **00:32** — ~40 min before the rider arrives |

LangGraph and the raw loop place the *identical* order (a conformance test proves
they're equivalent) — so the framework's value isn't fewer lines (it's 2x more), it's
checkpointed state and a real interrupt that the raw loop fakes with flags and would
lose on a restart. The naive baseline orders too early, for the nearest place, with no
LLM call: that `00:32` vs `01:12` gap is the whole product. Full write-up in
[`docs/framework-comparison.md`](docs/framework-comparison.md).

---

## Stack

- **LangGraph** — orchestration: graph state, checkpointing, interrupts
- **Foursquare Places API** — open restaurants + hours near the hotel (the one live call)
- **Mapbox** — airport → hotel ETA
- **Anthropic Claude** — the choice-set reasoning (one structured tool-use call)
- **ChromaDB** (in Docker) — the synthetic trip + Uber Eats order-history store;
  taste ranking and the confidence-gated cuisine classifier read from it
- **sentence-transformers + numpy** — local embeddings (all-MiniLM-L6-v2, no API)
- **FastAPI + SSE** — streaming the agent's reasoning to the browser
- Flight status and order placement are **mocked** — flight APIs are flaky, and
  there is no public Uber Eats consumer API. Honest constraints, not shortcuts.

See [`DESIGN.md`](./DESIGN.md) for the full design and the decisions behind it.

---

## Evals

The agent's value is *judgment*, which unit tests can't assert. After an eval audit,
`evals/` holds binary evaluators (no Likert), gold labels for both classes, and
**TPR/TNR validation** — including a rigorously validated LLM judge (train/dev/test +
bias correction) and a synthetic stress-test that tuned the cuisine classifier to
zero out-of-set false matches. The evals *found and fixed* real bugs (Korean-BBQ-as-
American misclassification, false "you order X most" copy, a JetBlue flight-code miss).
Full writeup in [`evals/README.md`](evals/README.md).
