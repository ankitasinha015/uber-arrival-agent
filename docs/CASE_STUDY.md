# Case study: an agent that knows when *not* to act

**One line:** Most trip apps send a notification. This one decides when to stay quiet.

A working, deployed agent that sits on top of Uber Travel Mode's room-service delivery. You're
arriving somewhere new. It watches the trip, predicts when you'll actually be in your hotel
room, and times the room-service order so dinner lands after you do, not before. Live demo:
`https://ankita015-uber-arrival-agent.hf.space/concierge`

---

## The problem

You land at 1am in a city you don't know, after a delay. Fixing dinner, the hotel hold, and
the ride means three apps and guesswork, at the exact moment you have the least patience and
the worst judgment. The status quo isn't a competitor product. It's the traveler doing it all
by hand, badly, while exhausted.

## Why an agent, not a notification

A notification says "you might be hungry." It pushes the work back onto you. This shows up
with a resolved, timed, supply-checked order: a real restaurant that's open now, near *this*
hotel, ranked by what you actually order, timed to land after you're in the room. The value is
everything behind the prompt already being solved: arrival prediction, supply check, continuous
re-timing, and recovery when a restaurant drops offline.

## The one hard decision: knowing when not to act

This is the whole thing. When the ride starts, the agent already has a tight arrival estimate.
It still waits. A naive version orders the moment the flight lands and delivers dinner at
**00:32**. The real agent holds until **01:12**, because ordering early means food waiting at
the front desk for 40 minutes while the traveler is still in the cab.

| Version | Orders at | Why |
|---|---|---|
| Naive (no judgment) | **00:32** | Nearest place, the moment the plane lands |
| This agent | **01:12** | Waits for a real room-arrival estimate, then acts |

Picking one restaurant out of fifty is search. Deciding *not* to order yet is judgment. That
40-minute gap is the entire argument for building an agent instead of a notification, and it's
the one thing I want someone to remember.

The same timing math does a second job. Uber Travel Mode books restaurant reservations
(OpenTable) *and* delivers room service, but it doesn't choose between them. This agent does:
if you'll clear the airport in time to make your table, it keeps the reservation; if you'll
land too late, it releases the table and switches to room-service delivery. One rule ("when
will you actually be there"), two decisions.

## How I kept it honest

An agent that recommends dinner can lie in small, plausible ways, and those lies are the ones
that erode trust. I built an evaluation program to catch them, and it caught real ones:

- A Korean BBQ place was being tagged as "American" and badged as a match for a burger lover.
- The copy claimed "you order this most" for a cuisine that wasn't the traveler's top choice.

I replaced the hand-written cuisine rules with a confidence-gated vector classifier and tuned
it against a 40-case synthetic stress test until it produced **zero out-of-set false badges**:
Korean BBQ, German, French, and sushi now show under their own name instead of a forced match.
The LLM judge that scores dinner-set quality is validated at **100% true-positive and
true-negative rate on a fresh 40-case held-out set**, using a proper train/dev/test split and
bias correction. Most product work can't show it evaluated a non-deterministic system. This can,
with receipts.

## Two tradeoffs I rejected

Rejected decisions show judgment more than shipped features do.

1. **Vector ranking for dinner.** The obvious "AI" move was to rank restaurants by embedding
   similarity to past orders. I built it, measured it, and it ranked *worse* (it put a burger
   place first for a Mexican lover). I cut it and kept cuisine-frequency ranking. Retrieval was
   never the bottleneck; scoring was.
2. **Bundled demo data.** I could have recorded restaurant results to make the deploy
   self-contained and deterministic. I rejected it. Every persona makes a real Foursquare and
   Mapbox call in production, because a portfolio piece that only works on a canned reel isn't
   proof of anything.

## How it's built (depth on tap, not the headline)

- A framework-agnostic core (the reasoning and tools, pure, no I/O) with three thin adapters:
  LangGraph (primary), a hand-rolled raw loop, and a deliberately dumb naive baseline. A
  conformance test proves raw and LangGraph place the identical order.
- LangGraph earns its extra lines here, not by being shorter (it's 344 lines to raw's 182) but
  by giving durable checkpointed state and a native interrupt for the human-in-the-loop pause,
  which the raw loop fakes with flags and would lose on a restart.
- Deployed live on Hugging Face Spaces. Synthetic traveler data in ChromaDB; restaurant geo is
  the one live external call.

## Positioning

Uber GO-GET 2026's Travel Mode shipped "room service" delivered to your hotel door (food and
forgotten essentials). Uber built the delivery rail; its own description says nothing about
*when*. This agent is the missing intelligence: the arrival-orchestration layer that predicts
when you'll be in your room and fires the Travel Mode room-service order so food lands after
you do. A working prototype of the judgment the rail doesn't have.
