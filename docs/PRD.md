# PRD: Uber Arrival Agent (Travel Mode × Eats)

**Status:** shipped (portfolio prototype) · **Author:** Ankita Sinha · **Last updated:** 2026-07

## TL;DR

An agent that sits between Uber's Travel Mode and Eats. It watches a trip, predicts when
the traveler will actually be in their hotel room, and at the right moment hands them a
dinner already timed to arrive after they do. Its defining behavior is restraint: it
decides *when not to act*. Live demo:
`https://ankita015-uber-arrival-agent.hf.space/concierge`.

## Problem

A traveler lands late, after a delay, in a city they don't know. Fixing dinner, the
hotel hold, and the ride means three apps and guesswork, at the moment they have the
least patience. The status quo is not a competing app. It is the traveler doing all of
it by hand while exhausted, and often getting the timing wrong (food waiting cold at the
front desk, or ordered too late to arrive before they crash).

## Target users

Late-night arriving travelers. Five segments, each stressing a different behavior of one
engine (see [`PERSONAS.md`](PERSONAS.md)):

| Segment | Who | What they need |
|---|---|---|
| First-time flyer | Nervous, unfamiliar airport | Tell me what to do and when; hold my hand |
| Road warrior | 45+ flights/yr | Do not nag me; surface only what I'd actually miss |
| On-time optimist | Smooth trip | Stay silent unless something breaks |
| Red-eye arriver | Flight got changed | Make the landing soft; re-sync everything |
| Creature of habit | Orders the same food | Do not make me choose; you already know |

## Goals and success metrics

| Goal | Metric | Target |
|---|---|---|
| Food arrives *after* the traveler, not before | Gap between order-delivery and room arrival | delivery lands 0–20 min after check-in, never before |
| Act only when the estimate is trustworthy | Wait when room-arrival uncertainty > tolerance | 100% (rule-enforced) |
| Suggestions are honest | Out-of-taste places wrongly badged | 0 (validated: 0/16 false badges on stress test) |
| Proportionate to the traveler | Actions surfaced vs traveler need | full list for HIGH, silence for NONE |
| Recover from disruption without a human babysitting | Delay/flight-change → downstream bookings re-synced | automatic, all arrival-coupled bookings |

## Non-goals (explicit)

- **Not autonomous ordering.** The agent never spends money or sends a message without a
  human tap. It curates and drafts; the pick and the send are the human's.
- **Not a payment product.** Payment is offstage (Uber's card-on-file). No payment UI.
- **Not a standalone venture.** The seam it owns (Travel Mode → Eats) belongs to Uber.
  This is a prototype of the missing orchestration layer, not a company.
- **Not real integrations.** Flight status and order placement are mocked; there is no
  public Uber Eats consumer API and flight APIs are flaky. Restaurant geo is the one live
  call.

## Requirements

**R1 — Watch the whole trip, act at moments.** One agent handles departure (leave-earlier
nudge), delay/flight-change (notify hotel + trip-sync), and arrival (welcome, exit-time,
dinner). One engine, multiple triggers.

**R2 — Know when not to act.** At arrival the agent must wait until the room-arrival
estimate is tight before ordering. This is the core requirement, spec'd in
[`TECH_SPEC_RETIMING.md`](TECH_SPEC_RETIMING.md).

**R3 — Design a choice set, not a single answer.** Surface 2–3 dinner options that vary
along an axis chosen for this traveler at this moment, ranked by their real Uber Eats
order history, with a one-line reason each.

**R4 — Be honest in copy.** Only claim "you order X most" for the traveler's #1 cuisine;
badge "matches what you order" only on a confident top-taste match; show ambiguous places
(Korean BBQ, German) by their own name with no forced badge. Enforced by the eval program
([`../evals/README.md`](../evals/README.md)).

**R5 — Trip-sync on disruption.** A delay or flight change auto-notifies the hotel, then
re-syncs every arrival-coupled booking (pickup, rental, dinner reservation) to the new
arrival, and hands off ride tracking. The agent reasons over the traveler's existing
bookings (e.g. a meet-&-greet pickup means no Uber is offered).

**R6 — Proportionate response.** An intensity dial (HIGH/LOW/NONE) scales the action list
to the traveler and the moment; behavior memory drops what a returning traveler always
dismisses.

**R7 — Recover in-thread.** A restaurant going offline is just the next action (drop the
dead option, backfill a replacement), not a special case.

## Key product decisions

1. **The wait rule is the product.** A naive version orders at flight-land (00:32); this
   agent waits until the room estimate is tight (01:12), a 40-minute gap. Restraint, not
   speed, is the differentiator.
2. **Agent proposes, human decides.** Reversible and free actions (drafting a note) run
   automatically; money, sends, and picks require a tap. This resolves the "can the agent
   act?" tension without an autonomy leap.
3. **Honesty over coverage.** The dinner ranking would rather abstain (show a place
   neutrally) than make a confident wrong claim. Trust is the currency.

## Constraints and assumptions

- Uber owns the trip context (Travel Mode has the itinerary). Assumed for the demo.
- Data is synthetic (ChromaDB); the traveler's taste comes from synthetic Uber Eats order
  history. Only restaurant geo is live.
- Portfolio scale: one traveler at a time, ~10–100 orders of history each.

## Risks and open questions

- **Timing assumptions are hand-tuned** (deplane 23 min, ride 30 min, check-in 12 min).
  Real distributions would replace these; the structure holds.
- **International exit time** is a flat longer estimate; real immigration/baggage variance
  is higher.
- **The choice-set axis** is currently deterministic (cuisine) in the live web path; the
  LLM axis-selection exists in the core and is validated but not wired to the web demo.

## Positioning

Uber GO-GET 2026's Travel Mode added "room service" delivered to your hotel door (food and
forgotten essentials), announced April 2026. Uber built the delivery rail; its own description
says nothing about *when* to order. This product is the missing intelligence: the arrival-
orchestration layer that predicts room arrival and times the Travel Mode room-service order so
food lands after the traveler does, not before.

## Appendix

- Product story: [`CASE_STUDY.md`](CASE_STUDY.md)
- Architecture: [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
- The wait-vs-act spec: [`TECH_SPEC_RETIMING.md`](TECH_SPEC_RETIMING.md)
- Design record + as-built: [`../DESIGN.md`](../DESIGN.md)
