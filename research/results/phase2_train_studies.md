# Phase 2 results — regime + time-of-day studies (train only)

Date: 2026-07-11. Runs: `r-20260711-200234-d1de39b0` (regime),
`r-20260711-200316-7e7648e4` (tod). Full per-variant records in
`research/ledger.jsonl`. 752 train sessions used by tod; 721 usable by the
regime session table (RTH coverage ≥ 300 min).

## Regime: FAILED (layer dead)

All 26 detector variants failed the pre-registered freeze gate
(separation bootstrap-t ≥ 2, coverage ≥ 20% per class, sign-stable across
2023/2024/2025). Range of outcomes:

| detector family | variants | best sep_t | coverage ok? | sign-stable? |
|---|---|---|---|---|
| band_breach (k×m grid) | 9 | +0.81 | mostly | no |
| open_drive (thr×m) | 9 | +0.23 | yes | no |
| gap (thr) | 2 | +0.02 | 1 of 2 | no |
| cumvol (thr×m) | 6 | −1.28 (all negative) | 2 of 6 | inverse |

Consequences (pre-registered): dependent families run unconditioned;
trend_continuation swaps in the causal structural trend condition recorded
in its spec addendum.

Exploratory anomaly (not actionable without new registration): cumvol ≥ 1.2
at minute 90 → sep_t −3.59, negative all three years. High relative volume
by 11:00 predicts LESS remaining drift.

## Time-of-day: no positive cell

Mean net R per canonical bracket (stop 1×atr_5m, horizon 60m) by 30-min
bucket, with session-block bootstrap-t. 1R/2R targets, both directions:

```
bucket       long_1r_60m      short_1r_60m       long_2r_60m      short_2r_60m
09:30     -0.077 (t-5.1)    -0.078 (t-5.3)    -0.063 (t-2.5)    -0.070 (t-2.8)
10:00     -0.060 (t-3.0)    -0.045 (t-2.2)    -0.051 (t-1.6)    -0.060 (t-1.8)
10:30     -0.060 (t-2.7)    -0.041 (t-1.8)    -0.080 (t-2.4)    -0.066 (t-1.9)
11:00     -0.033 (t-1.4)    -0.069 (t-2.8)    -0.051 (t-1.4)    -0.117 (t-3.4)
11:30     -0.018 (t-0.7)    -0.087 (t-3.5)    +0.009 (t+0.2)    -0.109 (t-3.0)
12:00     -0.029 (t-1.2)    -0.087 (t-3.5)    -0.017 (t-0.5)    -0.096 (t-2.7)
12:30     -0.057 (t-2.2)    -0.061 (t-2.4)    -0.013 (t-0.3)    -0.083 (t-2.2)
13:00     -0.043 (t-1.8)    -0.075 (t-3.1)    -0.020 (t-0.6)    -0.080 (t-2.2)
13:30     -0.053 (t-2.0)    -0.084 (t-3.3)    -0.014 (t-0.4)    -0.079 (t-2.1)
14:00     -0.025 (t-1.0)    -0.099 (t-4.0)    -0.003 (t-0.1)    -0.099 (t-2.7)
14:30     -0.068 (t-2.7)    -0.060 (t-2.4)    -0.090 (t-2.5)    -0.051 (t-1.4)
15:00     -0.104 (t-4.4)    -0.029 (t-1.2)    -0.127 (t-3.6)    -0.056 (t-1.5)
15:30     -0.044 (t-2.2)    -0.088 (t-4.3)    -0.024 (t-0.8)    -0.103 (t-3.7)
```

Reading: the market charges ~0.03–0.13 R per unconditional entry after
costs, everywhere. Any family that survives train gates has to earn its
whole edge from its entry conditions, not from a lucky time slot. Candidate
windows (tod-window-1 = 11:00–14:00, tod-window-2 = 10:30–15:00) are
recorded in the family specs.

## What this means for the program

Neither study found free structure. That is informative, not fatal: these
were the two cheapest hypotheses, and both were graded honestly against
pre-registered gates. Phase 3 families and the ML track now carry the
burden of proof under the same rules.
