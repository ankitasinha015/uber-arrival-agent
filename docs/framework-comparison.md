# Framework Comparison

The project deliberately separates a framework-agnostic **core** from per-framework
**adapters**, so the same agent can be evaluated across frameworks. This document is
the written half of that evaluation.

The project's shape decides the fit: **long-running, event-driven, stateful,
single-agent, human-in-the-loop at the choice moment.** This is not a chat agent
and not a multi-agent crew. That rules frameworks in and out hard.

| Framework | Core model | Fit | Built? |
|-----------|-----------|-----|--------|
| **LangGraph** | Graph / state machine, persistent state, checkpoints, interrupts | **Strong** — "wait then re-decide" is a graph transition; "surface choice set and wait for user pick" is a native interrupt | Yes (primary) |
| **Raw loop** | Hand-rolled tool-calling state machine | **Medium** — fine for the loop; you hand-build state persistence + the pause-for-pick | Yes (contrast) |
| **Naive baseline** | No re-timing, no choice-set design | **N/A** — built to lose, on purpose | Yes (strawman) |
| **CrewAI** | Role-based multi-agent crew | **Weak** — one agent doing predict/curate/recover; no real roles to assign | No — evaluation only |
| **AutoGen** | Conversational multi-agent | **Weak** — conversation-centric, not event-centric; a forced fit | No — evaluation only |

## Why CrewAI and AutoGen are evaluation-only

Building a forced fit teaches little and costs days. The honest finding — *why*
their core models do not match an event-driven single-agent project — is itself the
interview insight:

- **CrewAI** wants a crew of specialized roles collaborating. This agent is one
  actor making a sequence of judgment calls over time. Splitting it into fake roles
  ("Predictor", "Curator", "Recovery Agent") adds coordination overhead and obscures
  the actual logic.
- **AutoGen** is built around agents conversing to reach an outcome. The arrival
  agent is not in a conversation — it is reacting to external events (flight
  webhook, ride-started, order-rejected) on a timeline it does not control.

## LangGraph vs raw vs naive — the numbers

All three implement the same `ArrivalAgent` contract. Reproduce with
`arrival-agent --compare --scenario delayed-flight` (live; LangGraph + raw each
make one real LLM call):

| Adapter | LOC | Tool calls | LLM calls | Tokens | Runtime (s) | Ordered (restaurant @ delivery) |
|---------|-----|-----------|-----------|--------|-------------|---------------------------------|
| LangGraph | 344 | 6 | 1 | 1994 | 14.1 | Super Duper Burgers @ 01:12 |
| raw       | 182 | 6 | 1 | 1994 | 12.6 | Super Duper Burgers @ 01:12 |
| naive     | 53  | 3 | 0 | 0    | 1.95 | Ippudo @ 00:32 |

Two things the table proves, and one it sets up:

**LangGraph and raw place the identical order.** Same restaurant, same delivery
time, same tool + token cost. They are the same agent — the conformance test
(`tests/test_adapter_contract.py`) asserts they surface the same choice set and
place the same option on every run. The orchestration differs; the behavior does
not.

**The framework was not fewer lines — it was ~2x MORE (344 vs 182).** This is the
honest, slightly counter-intuitive finding. The win isn't brevity. What LangGraph
bought, the raw adapter had to hand-roll or do without:

- *Checkpointed state.* LangGraph's `MemorySaver` carries the accumulated events
  and the prediction across invocations on a thread, and would survive a process
  restart with a real checkpointer (SQLite/Postgres). The raw adapter holds state
  in instance attributes (`self._events`, `self._await`) — equivalent in one
  process, gone on restart. For a trip that spans hours, that durability is the
  point of the framework.
- *A real interrupt.* "Surface the choice set, wait for the pick" is a native
  LangGraph `interrupt()` — pause, persist, resume on `Command(resume=...)`. The
  raw adapter fakes it with an `_await` flag and a branch at the top of
  `handle_event` that re-routes events while parked. It works, but it's the kind
  of state machine you re-implement (slightly worse) every time.
- *Replay-safety as a constraint.* Because the checkpointer re-runs nodes on
  resume, the LangGraph adapter must keep the LLM call in its own node and
  serialize state to JSON-able dicts — extra lines the raw adapter skips by
  holding native objects. So some of LangGraph's LOC is the tax of correctness
  under replay, which the raw loop simply doesn't have to pay (and would get
  subtly wrong at scale).

Verdict: for a one-shot, single-process demo the raw loop is genuinely simpler
and lighter. The moment you want durable multi-hour state, crash recovery, or a
visualizable graph, LangGraph earns its extra lines. Choosing it here is choosing
the trajectory, not the line count.

**The naive baseline shows the cost of no judgment.** It skips re-timing and
choice-set design entirely: 0 LLM calls, and it orders the moment the ride starts
— delivering food at **00:32, roughly 40 minutes before the rider reaches the
room** (~01:12 in this run). One nearest option, no axis, no recovery. That gap
between `00:32` and `01:12` is the whole product in one cell: knowing *when* to
act, and designing a choice worth making, is the agent.

## V3: the controller is the core, the framework is durability

The trip concierge (V3) pushed the framework question one level cleaner. The whole
loop — present next to-do, run its series, pause at pick/send, check for next,
recover — lives in `core/domain/controller.TripController`, which has **zero
framework imports**. It is pure Python: no LangGraph, no I/O, no framework state.

So *who drives it* is an orchestration choice, not a logic one. `adapters/
concierge_drivers.py` gives it two drivers and a conformance test
(`tests/test_concierge_conformance.py`) proves they are equivalent:

| Driver | How it pauses | Behavior |
|--------|---------------|----------|
| **raw** | a plain `while` loop calling `start()` / `respond()` | — |
| **LangGraph** | one node looping on a native `interrupt()`, `MemorySaver` checkpointer | **identical** |

Both produce the *same pause sequence and the same outcomes*, including through a
recovery (restaurant offline → re-pause → pick the backup). `raw == LangGraph`.

### The live demo now runs on LangGraph (with durable state)

The running web app is no longer just the raw driver — each moment of a trip is
driven through `web/concierge_graph.py`, a compiled `StateGraph` whose single
node loops on a native `interrupt()`, checkpointed by a **`SqliteSaver`** on
disk. Every pause (pick / send / confirm_dish / snooze) is one interrupt,
persisted to `concierge_checkpoints.sqlite` under `thread_id = "{run_id}:{seg}"`.

Because the state is on disk, a paused trip is **durable across a process
restart** — `tests/test_concierge_langgraph_web.py` proves it: drive a moment to
its pause, throw the graph away, build a **brand-new graph + checkpointer on the
same db file**, and it resumes from disk (`Command(resume=…)`) to the identical
outcome. That's the crash-recovery the comparison below argues LangGraph is
*for*, now demonstrated end to end rather than latent.

**The browser reattaches after a restart, too.** Durable *controller* state isn't
enough — the browser also has to find its trip again. So a small SQLite store
(`web/concierge_store.py`) records `run_id → mode` and an append-only **event
log**. On reconnect to a run the in-memory registry lost (process restarted), the
web layer (`registry.reattach`) rebuilds the run, **replays the event log** to
redraw the conversation, then continues from the moment still paused in the
LangGraph checkpoint — skipping already-finished moments (detected via
`graph.get_state`). Proven with an actual two-process restart: server 1 pauses a
trip and is killed; a **fresh server process** reattaches, replays the thread, and
drives it to completion (`test_concierge_langgraph_web.py`, plus a live HTTP
restart).

Replay-safety in practice: the node re-runs on every resume, so the live
restaurant lookup is **memoized per hotel** (`concierge._arrival_find`) — the
choice set is identical across replays and a resumed pick still resolves. The one
residual caveat: resuming *exactly* mid-dinner-pick across a **process** restart
would want the choice set frozen at decision time (the record/replay cache does
this), since a fresh process re-fetches live geo; pausing anywhere else resumes
cleanly cross-process, as the live restart test shows.

That makes the finding from the arrival-agent comparison sharper, not weaker.
Because the loop is fully extracted from the framework:

- **The framework does not decide anything.** The agent's judgment (which to-dos,
  which axis, when to recover) is all in the pure core. Swapping LangGraph for a
  raw loop changes nothing the user sees.
- **What LangGraph buys is durable trip-state.** A real checkpointer (SQLite/
  Postgres) would let the loop resume mid-trip after a process restart — the flight
  is delayed for hours, the server redeploys, and the agent picks up exactly where
  it paused. The raw driver holds the controller in memory and loses that on
  restart, precisely the tradeoff the arrival-agent raw adapter had.
- **The interview line:** "I extracted the agent loop into pure core, so the
  framework is a deployment decision about durability, not an architecture decision
  about behavior. LangGraph and a hand-rolled loop drive it to byte-identical
  outcomes; I keep LangGraph for the checkpointing a multi-hour trip needs."
