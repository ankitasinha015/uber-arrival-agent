# Framework Comparison

The project deliberately separates a framework-agnostic **core** from per-framework
**adapters**, so the same agent can be evaluated across frameworks. This document is
the written half of that evaluation.

The project's shape decides the fit: **long-running, event-driven, stateful,
single-agent, human-in-the-loop at the spend boundary.** This is not a chat agent
and not a multi-agent crew. That rules frameworks in and out hard.

| Framework | Core model | Fit | Built? |
|-----------|-----------|-----|--------|
| **LangGraph** | Graph / state machine, persistent state, checkpoints, interrupts | **Strong** — "wait then re-decide" is a graph transition; "authorize payment" is a native interrupt | Yes (primary) |
| **Raw / Agent SDK** | Lightweight tool-calling loop | **Medium** — great for the loop; you hand-build state + the pause-for-auth step | Yes (contrast) |
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

## What the LangGraph vs Raw comparison should surface

TODO — fill in after both adapters are built:
- What LangGraph gave for free (checkpointing, interrupts, the state machine).
- What it cost (dependency weight, the mental model, debugging the graph).
- Where the raw loop was simpler, and where it quietly re-implemented LangGraph
  badly.
