# Error analysis — labeled failure catalog

**86 traces reviewed** (56 extraction, 30 ranking). **40 fail** (47%).

## Failure rates (share of all traces)

| Category | Count | Rate | Definition |
|---|---|---|---|
| `extract:airport-miss` | 8 | 9% | arrival airport not extracted (non-ASCII arrow, odd route line) |
| `extract:hotel-miss` | 24 | 28% | hotel not extracted (alt label 'Accommodation:' / inline prose) |
| `extract:arrival-miss` | 24 | 28% | arrival date or time not extracted (24h clock, numeric date) |

## Decisions (step 6 — fix vs. evaluator vs. accept)

- `extract:flight-miss` → **FIXED in the parser**: the airline-code regex now allows a digit (JetBlue `B6`, `F9`). 0 after the fix.
- `extract:airport-miss` → **FIXED** for the unicode arrow `→`; the residual is the terse SMS format (no `(XXX)` pattern) — the LLM path recovers it.
- `extract:hotel-miss` / `extract:arrival-miss` → **accept + LLM**: not worth piling more regexes on the parser; the LLM path (`use_llm=True`) recovers these (measured: accommodation/inline → 100%). The parser is the documented offline fallback, so accuracy is tracked, not gated.
- `rank:cuisine-misclass` / `rank:false-frequency` → **0 across all ranking traces** — the alias + badge-gating fixes hold at scale; guarded in CI by the `cuisine_match` / `honest_copy` evaluators (TPR/TNR = 1).
- `rank:all-fallback` → not a failure: honest degradation when no taste cuisine is open nearby (neutral copy, no badge).

## Labeled traces

| Trace | Surface | Pass | Categories |
|---|---|---|---|
| UA517-canonical | extraction | ✓ | — |
| UA517-arrow-unicode | extraction | ✓ | — |
| UA517-accommodation-label | extraction | ✗ | extract:hotel-miss |
| UA517-24h-time | extraction | ✗ | extract:arrival-miss |
| UA517-numeric-date | extraction | ✗ | extract:arrival-miss |
| UA517-terse-codes | extraction | ✗ | extract:airport-miss, extract:hotel-miss, extract:arrival-miss |
| UA517-inline-hotel | extraction | ✗ | extract:hotel-miss |
| DL288-canonical | extraction | ✓ | — |
| DL288-arrow-unicode | extraction | ✓ | — |
| DL288-accommodation-label | extraction | ✗ | extract:hotel-miss |
| DL288-24h-time | extraction | ✗ | extract:arrival-miss |
| DL288-numeric-date | extraction | ✗ | extract:arrival-miss |
| DL288-terse-codes | extraction | ✗ | extract:airport-miss, extract:hotel-miss, extract:arrival-miss |
| DL288-inline-hotel | extraction | ✗ | extract:hotel-miss |
| LH435-canonical | extraction | ✓ | — |
| LH435-arrow-unicode | extraction | ✓ | — |
| LH435-accommodation-label | extraction | ✗ | extract:hotel-miss |
| LH435-24h-time | extraction | ✗ | extract:arrival-miss |
| LH435-numeric-date | extraction | ✗ | extract:arrival-miss |
| LH435-terse-codes | extraction | ✗ | extract:airport-miss, extract:hotel-miss, extract:arrival-miss |
| LH435-inline-hotel | extraction | ✗ | extract:hotel-miss |
| AA118-canonical | extraction | ✓ | — |
| AA118-arrow-unicode | extraction | ✓ | — |
| AA118-accommodation-label | extraction | ✗ | extract:hotel-miss |
| AA118-24h-time | extraction | ✗ | extract:arrival-miss |
| AA118-numeric-date | extraction | ✗ | extract:arrival-miss |
| AA118-terse-codes | extraction | ✗ | extract:airport-miss, extract:hotel-miss, extract:arrival-miss |
| AA118-inline-hotel | extraction | ✗ | extract:hotel-miss |
| B6615-canonical | extraction | ✓ | — |
| B6615-arrow-unicode | extraction | ✓ | — |
| B6615-accommodation-label | extraction | ✗ | extract:hotel-miss |
| B6615-24h-time | extraction | ✗ | extract:arrival-miss |
| B6615-numeric-date | extraction | ✗ | extract:arrival-miss |
| B6615-terse-codes | extraction | ✗ | extract:airport-miss, extract:hotel-miss, extract:arrival-miss |
| B6615-inline-hotel | extraction | ✗ | extract:hotel-miss |
| AC759-canonical | extraction | ✓ | — |
| AC759-arrow-unicode | extraction | ✓ | — |
| AC759-accommodation-label | extraction | ✗ | extract:hotel-miss |
| AC759-24h-time | extraction | ✗ | extract:arrival-miss |
| AC759-numeric-date | extraction | ✗ | extract:arrival-miss |
| AC759-terse-codes | extraction | ✗ | extract:airport-miss, extract:hotel-miss, extract:arrival-miss |
| AC759-inline-hotel | extraction | ✗ | extract:hotel-miss |
| WN44-canonical | extraction | ✓ | — |
| WN44-arrow-unicode | extraction | ✓ | — |
| WN44-accommodation-label | extraction | ✗ | extract:hotel-miss |
| WN44-24h-time | extraction | ✗ | extract:arrival-miss |
| WN44-numeric-date | extraction | ✗ | extract:arrival-miss |
| WN44-terse-codes | extraction | ✗ | extract:airport-miss, extract:hotel-miss, extract:arrival-miss |
| WN44-inline-hotel | extraction | ✗ | extract:hotel-miss |
| BA285-canonical | extraction | ✓ | — |
| BA285-arrow-unicode | extraction | ✓ | — |
| BA285-accommodation-label | extraction | ✗ | extract:hotel-miss |
| BA285-24h-time | extraction | ✗ | extract:arrival-miss |
| BA285-numeric-date | extraction | ✗ | extract:arrival-miss |
| BA285-terse-codes | extraction | ✗ | extract:airport-miss, extract:hotel-miss, extract:arrival-miss |
| BA285-inline-hotel | extraction | ✗ | extract:hotel-miss |
| mexican-dominant@New York | ranking | ✓ | — |
| mexican-dominant@Berlin (intl) | ranking | ✓ | — |
| mexican-dominant@Los Angeles | ranking | ✓ | — |
| mexican-dominant@San Francisco | ranking | ✓ | — |
| mexican-dominant@Chicago | ranking | ✓ | — |
| mexican-dominant@Miami | ranking | ✓ | — |
| ramen-niche@New York | ranking | ✓ | — |
| ramen-niche@Berlin (intl) | ranking | ✓ | — |
| ramen-niche@Los Angeles | ranking | ✓ | — |
| ramen-niche@San Francisco | ranking | ✓ | — |
| ramen-niche@Chicago | ranking | ✓ | — |
| ramen-niche@Miami | ranking | ✓ | — |
| burger-common@New York | ranking | ✓ | — |
| burger-common@Berlin (intl) | ranking | ✓ | — |
| burger-common@Los Angeles | ranking | ✓ | — |
| burger-common@San Francisco | ranking | ✓ | — |
| burger-common@Chicago | ranking | ✓ | — |
| burger-common@Miami | ranking | ✓ | — |
| thai-forward@New York | ranking | ✓ | — |
| thai-forward@Berlin (intl) | ranking | ✓ | — |
| thai-forward@Los Angeles | ranking | ✓ | — |
| thai-forward@San Francisco | ranking | ✓ | — |
| thai-forward@Chicago | ranking | ✓ | — |
| thai-forward@Miami | ranking | ✓ | — |
| pizza-lover@New York | ranking | ✓ | — |
| pizza-lover@Berlin (intl) | ranking | ✓ | — |
| pizza-lover@Los Angeles | ranking | ✓ | — |
| pizza-lover@San Francisco | ranking | ✓ | — |
| pizza-lover@Chicago | ranking | ✓ | — |
| pizza-lover@Miami | ranking | ✓ | — |