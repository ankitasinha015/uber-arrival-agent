# Choice-Set Review Interface

A trace-level annotation app for the dinner **choice sets** the agent produces — the
most judgment-heavy output in the pipeline. A domain expert labels each whole trace
Pass/Fail/Defer: *is this a good, honest dinner suggestion?*

## Use

```bash
# 1. sample traces (sampling logic lives here, not in the app)
[CONCIERGE_CHROMA=1 HF_HUB_OFFLINE=1] python -m evals.export_review_traces   # → traces.js

# 2. serve + open (file:// is blocked by browsers; serve over HTTP)
python -m http.server 8099 --bind 127.0.0.1     # run from evals/review/
#   then open http://127.0.0.1:8099/index.html
```

## What it does

- Renders each trace like the product: traveler + taste chips, the ranked options with
  their badge and copy, the **honesty-bearing phrases bold-highlighted** ("order X
  most", "a lot"), and all candidates the agent ranked in a collapsible table.
- **Pass / Fail / Defer** + a free-text note, **auto-saved** to `localStorage` on every
  action (survives reload). Export to `labels.json` / `labels.csv`.
- Keyboard: `←`/`→` navigate · `1` Pass · `2` Fail · `D` Defer · `U` undo ·
  `⌘/Ctrl+S` save · `⌘/Ctrl+↵` save & next. Jump-to-id, progress bar, labeled/left tally.
- A **rubric panel** states the Pass criteria (real spread; honest frequency claims;
  no force-badging an out-of-taste place; picks actually near the hotel).

The sampled traces deliberately span the judgment space: clean taste matches, honest
abstains (Korean BBQ / German shown neutrally), weak fallbacks (nothing in-taste open
nearby), the italian-vs-pizza edge, and an international (Berlin) arrival.

Labels collected here feed back into gold sets / error analysis — this is the human
side of the [eval loop](../README.md).
