# Uber Arrival Agent

An agentic system at the seam between **Travel Mode** and **Eats**: it watches a
traveler's trip, predicts when they will reach their hotel room, finds food that is
actually open, and continuously **re-times** the delivery as real events arrive
(flight landed, ride started, restaurant went offline). The user authorizes the
payment with a single tap — the agent does everything else.

Portfolio / interview artifact. See [`DESIGN.md`](./DESIGN.md) for the full design.

## Why it is an agent, not a notification

The value is everything *behind* the prompt being already solved: arrival-time
prediction, supply check, continuous re-timing, and recovery when a restaurant goes
offline. The hard part — and the interesting part — is the agent choosing to
**wait** because acting early would fail.

## Architecture

A framework-agnostic **core** with per-framework **adapters**, so the same agent can
be run on different agentic frameworks and compared.

```
src/arrival_agent/
  core/            framework-agnostic
    tools/         flight (mock), restaurants (Yelp), eta (Maps), orders (mock)
    domain/        re-timing calculator, recovery policy, delegation envelope
    events.py      event model: flight webhook, ride-started, order-rejected
    contract.py    the agent-loop contract every adapter implements
  adapters/
    langgraph/     primary implementation (best fit: stateful, event-driven, HITL)
    raw/           roll-your-own contrast implementation
docs/
  framework-comparison.md   LangGraph vs raw vs CrewAI vs AutoGen
scenarios/
  delayed-flight.json       mock event timelines for the demo
```

## Stack

- **LangGraph** — orchestration (graph state, checkpoints, interrupts)
- **Yelp Fusion API** — open restaurants + hours near the hotel
- **Maps API** — airport -> hotel ETA
- **LLM** — the agent reasoning
- Flight status and order placement are **mocked** (flight APIs are flaky; there is
  no public Uber Eats consumer API)

## Setup

```bash
cp .env.example .env   # fill in API keys
pip install -e .
```

## Status

Scaffolded. Implementation in progress — see `DESIGN.md` "Next Steps".
