# Phase 3 results — rule families + ML track (train, cycle 1)

Date: 2026-07-11. 760 grid points evaluated across five families, all
registered before evaluation (runs `r-20260711-201203` vwap_reversion,
`-201314` orb, `-201409` trend_continuation, `-201442` levels,
`-2013xx/2020xx` ml — full records in `research/ledger.jsonl`).

## Verdict: ZERO survivors

| family | grid | passers | best point (diagnostics) |
|---|---|---|---|
| vwap_reversion | 216 | 0 | PF 1.33, n=190, t=1.7 — fails months+, top10, t |
| orb | 192 | 0 | PF 1.14, n=236, t=0.9 — fails everything that matters |
| trend_continuation | 128 | 0 | PF 1.64, n=57, t=1.6 — too rare, concentrated |
| levels | 192 | 0 | PF 1.84, n=75, t=2.6 — fails n>=150, top10<40% |
| ml (logistic + HGB) | 32 | 0 | PF 0.97 — sub-breakeven out-of-fold |

Train gates required: PF >= 1.25, n >= 150, >= 60% months positive,
top-10-trade share < 40%, session-bootstrap t >= 2, PF > 1.0 at 1.5x
slippage, plateau (neighbor median PF >= 1.15). Winrate was recorded,
never selected on.

## Reading the failures honestly

- **ML is the cleanest null.** Ten expanding walk-forward folds, ~53k
  training rows by the end, two model classes, causal theta calibration —
  and the best policy loses $0.95/trade after costs. If tabular patterns at
  1m resolution were there, this is where they had room to show.
- **levels-break is the most interesting near-miss**: first touches of
  prior-day/overnight levels after a >= 10x atr_1m approach, traded in the
  break direction, show PF 1.6-1.8 with t >= 2 on several neighboring grid
  points. But 55-91 trades in three years and top-10 shares over 40% mean
  it is exactly the shape of thing the gates exist to block: rare,
  concentrated, unverifiable at this sample size. The loosened variants
  already in the grid (approach=5) decay — the pattern does not scale up.
  Not promoted; noted for a possible future cycle when more sessions exist.
- **The scalp geometry is structurally hostile**: the tod study showed the
  market charges 0.03-0.13 R per unconditional entry; nothing in these
  grids overcame that plus the concentration gates.

## Consequences (pre-registered)

- No candidate advances to validation. Validation look budgets are intact
  (2 per family); the single holdout look is unburned.
- No engine integration, no paper gate, **no live signal-trading** from
  this cycle. The app remains the journal/discipline layer.
- The infrastructure (feature store, sim-1, gates, ledger, CV harness) is
  the durable asset: future cycles re-run cheaply as new sessions
  accumulate or new hypotheses are registered.
