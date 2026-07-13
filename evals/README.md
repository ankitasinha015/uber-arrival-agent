# Evals

The agent's value is its *judgment*, and judgment is exactly what unit tests can't
assert. So the agent's two judgment-heavy outputs get evals, using the three methods
that actually work on LLM output.

Run:

```bash
python -m evals.run                  # offline: properties + extraction
EVAL_LIVE=1 python -m evals.run      # + the LLM-as-judge quality score (needs a key)
```

## What's evaluated

### 1. Choice-set design (`choice_set_eval.py`)

The single LLM call that picks the axis and designs the 2-3 dinner options. Two methods:

**Property-based (offline, a regression baseline).** Hard invariants that must hold on
every choice set, run over the recorded golden outputs in `scenarios/cache/choice_set/`:

- axis is a real `ChoiceAxis`
- 2-3 options, never 1 or 4
- distinct restaurants (no dupes)
- positive totals, a rationale on every option, a rationale for the set, a reasoned axis

If a prompt change starts producing 4 options or an off-enum axis, this goes red in CI
(`tests/test_evals.py`). Current: **3/3 golden sets pass all invariants.**

**LLM-as-judge (quality).** Correctness isn't the same as *good*. A judge model scores
each set 1-5: do the options genuinely vary along their stated axis in a way useful to a
tired late-night traveler? Quality can't be asserted, so we measure it and watch the mean.

Real run: **mean 4.3/5.** Two sets scored 5/5 ("clear progression from light snack to
heavy feast"). One scored **3/5** with a specific critique: *"options span speed vs
quality but price intrudes unexpectedly, and quality conflates with portion size."* That
is the eval doing its job — it caught a muddy axis a pass/fail check never would.

### 2. Itinerary extraction (`extraction_eval.py`)

Reading the booking email into `{flight_no, airport, hotel, scheduled_arrival}`.
Field-level accuracy over emails in different formats. Offline runs the deterministic
parser; the point is to **surface where it breaks**:

- canonical format: **100%**
- variant format ("Accommodation:" instead of "hotel:"): **75%** — misses `hotel`

That miss is not a bug to hide, it's the finding: the deterministic parser handles the
format it was built for; robust extraction across formats is what the LLM path
(`use_llm=True`) is for. The eval quantifies the gap instead of pretending it's covered.

## Why these three methods

- **Property-based** catches structural regressions cheaply and deterministically — the
  CI gate.
- **LLM-as-judge** measures the subjective quality that invariants can't, and gives
  actionable critique, not just a number.
- **Accuracy-on-a-dataset** turns "does extraction work?" into a number that moves when
  you change the prompt or the parser, and honestly shows what isn't covered yet.

Judge scores drift a little run to run (it's a live model call). For a real gate you'd
run each case N times and average, or pin a seed; here the mean over three sets is stable
enough to trend.
