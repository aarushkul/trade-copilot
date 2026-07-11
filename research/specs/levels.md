# Spec: levels — prior-day/overnight level reactions (family f)

**Status:** DRAFT — grid frozen at first ledger registration.

## Hypothesis (falsifiable)
First touches of PDH/PDL/PDC/ONH/ONL after an approach from distance produce
tradeable reactions whose direction depends on regime: rejection (fade) in
range regimes, acceptance (break-through continuation) in trend regimes.
Unconditioned, the two cancel — which is why the old key_levels voter added
nothing. If neither conditioned arm passes train gates, levels are decoration.

## Entry (feature terms)
- level set: {PDH, PDL} / {+PDC} / {+ONH, ONL} (three nested arms)
- first touch of the session only; approach ≥ {5, 10} × atr_1m from ≥ 30 min away
- fade arm: rejection close (wick through, close back) within {1, 3} bars, regime ∈ {range, any}
- break arm: 1m close through by ≥ {0.25, 0.5} × atr_5m with rvol ≥ 1.2, regime ∈ {trend, any}
- window ∈ {full RTH, tod windows}

## Exit
- stop: beyond the level/extreme by {0.5, 1.0} × atr_5m (5–45 pt clamp)
- target: {1R, 2R}; horizon 60 min

## Grid ≈ 3·2·(2·2 + 2·2)·2·2·3 ≈ 288 → prune ≤ 200 at freeze. Expected: 0–2 trades/session.

## Pre-registration addendum — 2026-07-11, before first registration
Regime layer FAILED (see regime.md): fade arm regime collapses to {any},
break arm regime collapses to {any}. tod windows fixed: tod-window-1 =
11:00–14:00 ET, tod-window-2 = 10:30–15:00 ET, plus full RTH.
