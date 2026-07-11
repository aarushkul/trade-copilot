# Spec: trend_continuation — pullbacks on confirmed trend days (family d)

**Status:** DRAFT — grid frozen at first ledger registration.

## Hypothesis (falsifiable)
On genuine trend days, the first 1–3 pullbacks to dynamic support (EMA21 /
VWAP) hold and continue; the edge concentrates mid-session (10:30–15:00)
after the trend is identifiable. If regime-gated continuation can't pass
train gates, intraday trend-following doesn't clear retail costs on MNQ.

## Entry (feature terms)
- regime = trend (its direction sets trade direction); detected by minute ≤ 90
- pullback: retrace to within {0.25, 0.5} × atr_5m of {ema21_1m, session VWAP}
  without closing beyond it against trend by > {0, 0.25} × atr_5m
- resumption trigger: 1m close back in trend direction with rvol ≥ {none, 1.0}
- pullback index ≤ {2, 3} of the session; window ∈ {10:30–15:00, tod windows}

## Exit
- stop: beyond pullback extreme by {0.25, 0.5} × atr_5m (5–45 pt clamp)
- target: {1.5R, 2R} OR trail-to-close arm

## Grid ≈ 2·2·2·2·2·2·2·3 ≈ 192. Expected: 0–2 trades/session (trend days only).

## Pre-registration addendum — 2026-07-11, before first registration
Regime layer FAILED (see regime.md), so "regime = trend" is replaced by a
causal structural trend condition, fixed here before registration:
price on one side of session VWAP for ≥ {60, 120} consecutive minutes
(vwap_side_min) with ema21_1m_slope sign agreement; that side sets trade
direction. Windows: {10:30–15:00 (as specced), tod-window-2 = 10:30–15:00
is identical, so the alternate is tod-window-1 = 11:00–14:00 ET}.

## RESULT — 2026-07-11, train (cycle 1)
**FAILED — 0 grid points passed train gates.** See
research/results/phase3_train_families.md and the ledger for per-point
records. Not promoted to validation; look budget intact.

## RESULT — 2026-07-11, cycle 1b (train extended to 2019)
**FAILED again — 0 points passed** on 1,680 train sessions. See
research/results/cycle1b_extended_train.md. Look budgets still intact.
