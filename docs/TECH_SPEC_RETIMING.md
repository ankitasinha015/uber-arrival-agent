# Tech spec: re-timing and the wait-vs-act rule

The agent's hardest decision is knowing *when not to act*. This spec covers the pure
domain logic that makes it: [`core/domain/retiming.py`](../src/arrival_agent/core/domain/retiming.py).
No I/O, no LLM, no tool calls. Adapters call it and surface its reason.

## The decision in one line

> Order dinner only once the *room-arrival* estimate is tight enough that the food won't
> land while the traveler is still in transit, and no earlier than it has to.

Acting too early leaves food at the front desk while the rider is still in customs. Acting
too late leaves no prep time. Both are failures; the rule threads between them.

## Inputs

`decide_timing(events, *, now, scheduled_flight_arrival, current_ride_eta_min, …)` takes:

- `events` — the trip's `TripEvent` list so far (booked, flight status, ride started/ended,
  check-in).
- `now` — current time (injected, so the logic is deterministic and testable).
- `scheduled_flight_arrival` — from the itinerary; needed when only `trip_booked` is known.
- `current_ride_eta_min` — the live Mapbox ETA the adapter fetched at `ride_started`.
- tunables — cold-food tolerance, safety margin, prep/courier minutes, delivery target,
  and a `user_response_buffer_min` (see below).

## Step 1: estimate room arrival (with a confidence)

`estimate_room_arrival` walks from the strongest signal to the weakest and uses the first
match. The estimate tightens monotonically as better signals arrive:

| Grade | Anchor | + expected ground time | Uncertainty (± min) |
|---|---|---|---|
| `trip_booked` | scheduled arrival | deplane 23 + ride 30 + checkin 12 | **90** (loose) |
| `flight_delayed` | estimated arrival | 23 + 30 + 12 | **50** |
| `flight_on_ground` | actual arrival | 23 + 30 + 12 | **35** |
| `ride_started` | ride start | live ETA + checkin 12 | **8** (tight) |
| `ride_ended` | ride end | checkin 12 | **5** |
| `check_in` | now | 0 | **2** (anchor) |

Returns an `ArrivalEstimate{estimated_at, uncertainty_minutes, grade, derived_from}`.

```
  trip_booked  ────────────────────────────────────────────▶  ±90
  flight delayed  ──────────────────────────────▶  ±50
  flight on_ground  ──────────────────▶  ±35
  ride_started  ────────▶  ±8      ← usually the first "tight enough" signal
  ride_ended  ──▶  ±5
  check_in  ▶  ±2
  (uncertainty shrinks as stronger events arrive)
```

## Step 2: the place-by deadline

`place_order_by(room_arrival)` computes the latest moment to order and still hit the
delivery target:

```
  target_delivery = room_arrival + deliver_after_arrival (20 min)
  place_by        = target_delivery − prep (15) − courier (12)
```

So food is aimed to land ~20 min after the traveler is in the room, and the kitchen +
courier need 27 min, giving the place-by deadline.

## Step 3: the rule

```
  ACT  when   uncertainty(room_arrival) ≤ cold_food_tolerance (10 min)
        AND   now ≥ place_by − safety_margin (3) − user_response_buffer

  else WAIT
```

Two independent gates, both must pass:

1. **Confidence gate.** If the estimate is looser than the cold-food tolerance, WAIT no
   matter the clock. At `±90` (trip booked) or `±50` (delayed), a single estimate error
   translates 1:1 into food sitting cold. Acting on a loose estimate *is* the failure mode.
   In practice the estimate first clears this gate at `ride_started` (±8 ≤ 10).
2. **Deadline gate.** Even with a tight estimate, don't act until close to the place-by
   deadline. No reason to commit early.

The returned `TimingDecision{action, reason, estimate, place_by}` carries a human-readable
reason the adapter shows ("estimate is ±50 min (from flight_delayed); acting now risks food
arriving while the rider is still in transit").

## The human-on-the-critical-path buffer

In the choice-set product the human is in the loop: the agent surfaces options, the user
picks, *then* the order is placed. Surfacing at the last possible second gives the user no
time to choose. So adapters pass `user_response_buffer_min` (~20 min): the choice set
appears as soon as the estimate is tight, leaving the user room to pick before the deadline.
The pure order-timing math (buffer 0) is unchanged for non-human callers.

## Worked example (why 00:32 vs 01:12)

```
  21:47  flight delayed              estimate ±50  → WAIT (confidence gate fails)
  00:20  flight on_ground            estimate ±35  → WAIT (still too loose)
  00:32  ride_started, ETA 28 min    estimate ±8   → confidence gate PASSES
                                      room_arrival ≈ 01:12, place_by ≈ 00:45
                                      with user buffer → ACT now, surface the choice set
  01:12  (target) food lands ~01:32, ~20 min after check-in
```

The **naive** adapter ignores the confidence gate and orders at the first arrival signal
(≈00:32 delivery), 40 minutes before the rider reaches the room. That 00:32-vs-01:12 gap is
the whole product in one number.

## Constants (all overridable via `decide_timing` kwargs)

| Constant | Value | Meaning |
|---|---|---|
| `DEPLANE_AND_BAGS_MIN` | 23 | gate → curb |
| `DEFAULT_RIDE_MIN` | 30 | ride fallback when no live ETA |
| `CHECK_IN_QUEUE_MIN` | 12 | hotel → in room |
| `DEFAULT_COLD_FOOD_TOLERANCE_MIN` | 10 | the confidence gate threshold |
| `DEFAULT_SAFETY_MARGIN_MIN` | 3 | slack before the place-by deadline |
| `DEFAULT_PREP_MIN` / `DEFAULT_COURIER_MIN` | 15 / 12 | kitchen + courier |
| `DEFAULT_DELIVERY_AFTER_ARRIVAL_MIN` | 20 | aim food to land 20 min after arrival |

## Failure modes and edge cases

| Case | Behavior |
|---|---|
| Only `trip_booked`, no `scheduled_flight_arrival` | raises `ValueError` (can't estimate) — caller must supply the itinerary |
| `ride_started` but no live ETA | falls back to `DEFAULT_RIDE_MIN` (30), uncertainty still ±8 |
| Multiple events of one type | uses the latest by timestamp (`_latest`) |
| Estimate tight but well before deadline | WAIT with "still N min before place-by" |
| Clock passes deadline | still ACT (better late than never); reason notes the window |

## Where it lives and how it's driven

- Pure module: `core/domain/retiming.py`. No framework imports.
- Adapters call `decide_timing` at each event and act on `action`/`reason`. The rule is
  identical across LangGraph and raw; the naive adapter is wired to ignore the wait
  recommendation, which is exactly the contrast the framework comparison measures
  ([`framework-comparison.md`](framework-comparison.md)).
- Determinism: `now` and `current_ride_eta_min` are injected, so the whole decision is a
  pure function of its inputs and unit-testable without a clock or network.

## Testing

Because it's pure, every branch is a table test: feed an event list + `now`, assert
`action` and `grade`. The high-value cases are the confidence-gate boundary (±8 vs ±10
tolerance), the deadline-gate boundary (now vs `act_at`), and the `trip_booked`-without-
itinerary `ValueError`.
