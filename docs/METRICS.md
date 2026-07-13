# Metrics — Trip Concierge

How you'd measure whether this agent is actually working. One North Star, the inputs
that move it, and the guardrails that keep an agentic product from decaying into spam.

## North Star

> **Handled trip moments per active traveler / month**
> A *handled moment* = the agent proposed a to-do and the user **approved** it (sent the
> hotel note, picked dinner, acted on a nudge).

It captures all three things that matter at once: the agent did real work, the user
*accepted* it (value, not activity), and it recurs across the trip. It correlates with
Uber's money (approved dinners → Eats orders) without being a vanity capture number.

**Instrumentation:** one `moment_handled` event per approved to-do
`{user_id, trip_id, moment, action_kind, ts}`. NSM = count / distinct active travelers.

## The funnel (input metrics)

The North Star breaks into an activation → engagement → quality chain. Watch where it
leaks.

| Stage | Metric | Definition | Event |
|---|---|---|---|
| Activation | **Opt-in rate** | % of eligible trips where the traveler lets the agent help at all | `agent_offered` → `agent_opted_in` |
| Engagement | **Approval rate** | approved to-dos / surfaced to-dos | `todo_surfaced` → `todo_approved` |
| Engagement | **Moment coverage** | distinct moment types handled per trip (of departure/delay/arrival) | derived from `moment_handled` |
| Friction | **Time-to-approve** | median seconds from surface to tap | `todo_surfaced` → `todo_approved` |
| Learning | **Memory lift** | Δ approval-rate for returning vs first-trip travelers | cohort on `trip_index` |

Approval rate is the sharpest input: it's the direct read on whether the *curation* is
good — is the agent surfacing the right to-do at the right moment?

## Guardrails (the counter-metrics that keep it honest)

The product's core bet is **knowing when *not* to act.** These are the metrics that go
red if the agent forgets that. Treat them as ship-blockers, not nice-to-haves.

| Guardrail | Catches | Target |
|---|---|---|
| **Dismiss rate** | the agent surfacing junk — the "acts too much" failure | trend down; alert if > baseline |
| **Timing accuracy** | food landing far from actual room arrival (the naive baseline's `00:32` failure) | delivered within ±10 min of arrival |
| **Recovery success rate** | a dropped restaurant dead-ending the flow | recovered before the user bails |
| **Unwanted-action rate** | the agent sent/acted when the user didn't want it (premise violation) | ~0; any occurrence is a P1 |
| **Opt-out / notification fatigue** | the ultimate "you annoyed me" | trend flat/down |

**Instrumentation:** `todo_dismissed`, `delivery_vs_arrival_min` (signed), `recovery_{attempted,succeeded}`, `unwanted_action_reported`, `agent_opted_out`.

## Business capture (the Uber lens)

| Metric | Why |
|---|---|
| Concierge-attributed Eats GMV / order rate | direct revenue from handled dinners |
| Reserve-ride attach | the airport→hotel leg + Eats-for-the-Way |
| **Retention lift (concierge users vs holdout)** | the real prize — an agent that handles your trip is a reason to keep Travel Mode / One |

Retention lift is measured against a randomized holdout, not correlation.

## The one-liner

North Star is *handled moments per traveler* — the agent did work the user accepted. But
the metric to watch hardest is the **dismiss rate**, because the product's whole design
exists to know when not to act. If dismissals climb, the agent has become a notification,
which is the exact failure the design avoids. Measure value with the North Star; protect
it with the dismiss-rate guardrail.
