# Spec: orderflow — aggressor-flow features from the NQ tape (family g)

**Status:** DRAFT — grid frozen at first ledger registration.
**Registered:** 2026-07-11, BEFORE any flow data was pulled or inspected.

## Hypothesis (falsifiable)
Per-minute aggressor-side flow aggregates from the **e-mini NQ** tape (delta,
imbalance, absorption, large-lot delta) carry exploitable signal for MNQ
bracket trades at 30-60 min horizons after retail costs. Literature: order
flow imbalance robustly predicts returns at second-to-minute horizons with
fast decay (Cont-Kukanov-Stoikov 2014; arXiv 2508.06788 E-mini SVAR, 2025).
The open question is whether ANY residual survives at retail horizons and
costs. If neither the rule grid nor ML-with-flow passes the standard train
gates, order flow at this timescale is dead for this program and the
"AI + more data" hypothesis dies with it at 1m resolution.

## Why NQ flow (not MNQ)
Institutional flow trades the e-mini; arbitrage locks MNQ to it within
ticks. Micro-contract flow is dominated by retail noise. Signal source = NQ
trades; fills/prices remain the existing MNQ bars through sim-1 unchanged.

## Data
- GLBX.MDP3 `trades` schema, NQ front-month per-contract raw symbols on the
  same expiry-8d roll calendar as the MNQ corpus; aggregated to per-minute
  buckets [t, t+60) aligned to MNQ bar timestamps.
- Range: as much of 2019-05..2026-07 as fits a ~$40 credit cap (dry-run
  quoted first; actual range recorded below at pull time).
- **Side-convention check (decode verification, not a tunable):** minute
  delta must correlate POSITIVELY with the same minute's MNQ return
  (documented contemporaneous OFI-return relation) in EVERY year pulled;
  if negative everywhere, the side mapping is inverted and fixed once.

## Flow feature columns (all causal, per closed minute)
fl_delta, fl_imbalance (delta/total), fl_delta_5m, fl_delta_15m,
fl_cumdelta (session), fl_intensity_vs_14d (trades/min vs same-minute
trailing-14-session mean), fl_avg_size, fl_big_delta + fl_big_imbalance
(trades >= 10 NQ lots), fl_absorption in {-1,0,+1} (price within
0.25 x atr_5m of the rolling 30m extreme while 5m imbalance points the
other way). fwd_* firewall applies unchanged.

## Rule grid (axes frozen here)
- **absorption_fade**: at rolling-30m extreme proximity (<= 0.25 x atr_5m),
  5m imbalance against the move >= {0.15, 0.25} -> fade; stop = beyond
  extreme + {0.5, 1.0} x atr_5m; target {1.0, 1.5}R; horizon 60;
  window {rth, w1}. (2*2*2*2 = 16)
- **delta_break_confirm**: 1m close beyond rolling-30m extreme WITH 5m
  imbalance in break direction >= {0.2, 0.3}; stop {1.0, 1.5} x atr_5m;
  target {1.0, 2.0}R; horizon 60; break before {720}; window rth. (16)
- **divergence_reversal**: new rolling-30m extreme while 15m delta sign
  opposes the 15m price change, |fl_delta_15m|/vol15 >= {0.1, 0.2} ->
  reversal; stop beyond extreme + {0.5, 1.0} x atr_5m; target {1.0, 1.5}R;
  horizon 60; window {rth, w1}. (32)
Total 64 rule points.

## ML-v2 arm (same registration discipline, family "ml")
Identical harness to ml-v1 (expanding quarterly walk-forward, embargo 1
session, causal theta = fold-train quantiles, sim-1, train gates), features
= v1 causal set PLUS the flow columns, restricted to sessions with flow
coverage. Diagnostic reference: ml-v1 best OOS PF 0.98 — but the gate is
the gate; beating 0.98 without passing gates is still a fail.

## Gates
The standard pre-registered train gates, unchanged. Survivors, if any,
resume Phase 4 under the untouched look budgets.

## Pre-pull addendum — 2026-07-11, after cost quotes, BEFORE any data pull

Quoted rates (NQ, per year): trades ~$122, tbbo ~$203, ohlcv-1s ~$42,
bbo-1s ~$24. Full-range raw trades ($827) exceeds the entire credit
balance, so the registered design is amended as follows, blind to results:

- **Flow source = NQ ohlcv-1s, tick-rule proxy** (sign(close-open) per 1s
  bar; doji -> sign vs previous 1s close; still flat -> volume split
  50/50), aggregated to per-minute buy/sell volume. No per-trade sizes
  exist in this schema, so fl_avg_size / fl_big_* are DROPPED from the
  feature set. Activity proxy = count of active seconds per minute.
- **Coverage = 2025-01-01 -> 2025-12-10 (train end)** — the most recent
  full train year, chosen for regime recency. ~236 train sessions,
  11 months. All gates unchanged; this is a reduced-power test and any
  verdict is scoped to "1s tick-rule flow proxy, one year".
- **Proxy validation**: one month of true NQ trades (2025-11-10 ->
  2025-12-10, ~$10) used ONLY to correlate proxy minute-delta vs true
  aggressor minute-delta. Proxy is credible if corr >= 0.8; below that,
  the family verdict is "proxy too weak", not "order flow dead".
- **ML-v2 folds**: with one covered year, quarterly folds are too few;
  ML-v2 uses expanding MONTHLY walk-forward (min 3 months train, embargo
  1 session) over the flow-covered sessions.
- **Staged spending rule**: if (and only if) something passes train gates,
  remaining credits may buy true trades for the same year to confirm
  BEFORE any validation look is considered.

## RESULT — 2026-07-12, cycle 2 (train, 241 covered sessions)
**FAILED, scoped as "proxy too weak" per the pre-pull addendum.** The
credibility gate failed (corr proxy vs true delta 0.706 < 0.8; rolled
windows 0.74-0.76). Rules 0/40 (best PF 1.12), ml-v2 0/32 (best PF 1.06).
Side decode verified correct (+0.686). Order flow remains UNTESTED at
full fidelity; a real test costs ~$122/yr of trades data. See
research/results/cycle2_orderflow.md.

## Full-fidelity plan — registered 2026-07-12, BEFORE purchase or pull

User-approved next step: buy true NQ trades for 2025-01-01 -> 2025-11-10
(~$112; merges with the existing val-month trades file to cover the full
train year). FLOW_VERSION bumps to 2 (features computed from TRUE aggressor
delta; big-lot columns fl_big_delta/fl_big_imbalance restored since sizes
exist). Evaluation: identical frozen rule sub-grids (orderflow-v2
registration) and identical ml-v2 axes with monthly folds, same gates.
The proxy-credibility gate is replaced by the side-decode check only
(already PASSED on this exact data source). Staged rule stands: no
validation look may be considered on flow results without a full-fidelity
train pass first. This section written blind — no true-trades data beyond
the already-validated month has been seen.

## Horizon study — registered 2026-07-12 BEFORE evaluation (user-directed)

One month of true trades (2025-11-10..12-10, ~21 train sessions) cannot
pass/fail the strategy gates (one month; n and months gates unreachable) —
instead it powers a descriptive information-horizon study on ~8k RTH
minutes: pooled Pearson corr of {delta_1m, imb_5m, imb_15m} vs NET forward
MNQ close-to-close moves at {1, 5, 15, 30, 60} min, RTH-only, forward
window within session; session-block bootstrap 95% CI (10k, seed 7).

Decision rule, stated blind:
- POSITIVE CONTROL: corr(delta_1m, fwd 1m) must be positive with CI
  excluding 0 — else the instrument is broken and nothing else is read.
- 30m and 60m columns (imb_5m, imb_15m): |corr| >= 0.05 with CI excluding
  0 -> buying the full 2025 trades year ($112) is justified;
  0.03-0.05 -> gray, user decides; < 0.03 or CI spans 0 -> flow carries no
  bracket-horizon information; recommend NOT buying for this strategy
  class. (Rough toll math: ~1.25 pts round-trip cost vs ~25 pt 60m sigma
  needs corr ~0.05 at 1-sigma selectivity to break even.)
