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
