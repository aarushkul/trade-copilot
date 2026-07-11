# Spec: vwap_reversion — band fades in range regimes (family b)

**Status:** DRAFT — grid frozen at first ledger registration.

## Hypothesis (falsifiable)
In detected range regimes, touches of outer VWAP σ-bands revert toward VWAP
often enough to clear costs; the old engine's vwap_fade lost because it also
faded trend days. If regime-conditioned fades don't pass train gates, the
reversion edge doesn't exist at these costs.

## Entry (feature terms)
- regime = range (or grid arm: unconditioned, only if regime layer froze dead)
- price crosses beyond VWAP + k·σ (short) / below VWAP − k·σ (long), k ∈ {1.5, 2.0, 2.5}
- inside the noise band (beyond-band fades are the old, measured mistake)
- optional confirmation arm: rejection close back inside band OR rsi_1m
  reversal cross (∈ {none, rejection, rsi})
- session window ∈ {full RTH, tod-window-1, tod-window-2} (from tod study)

## Exit
- stop: beyond the local extreme by {0.5, 1.0} × atr_5m
- target: VWAP touch OR fixed {1R, 1.5R}; horizon {60 min, hold-to-close-window}

## Grid size ≈ 3·2·3·2·2·2 ≈ 144 points. Expected frequency: 0.5–2 trades/session.

## Pre-registration addendum — 2026-07-11, before first registration
Regime layer FAILED (see regime.md): the regime arm collapses to
"unconditioned" per the grid note above. tod windows fixed from the tod
study: tod-window-1 = 11:00–14:00 ET, tod-window-2 = 10:30–15:00 ET.

## RESULT — 2026-07-11, train (cycle 1)
**FAILED — 0 grid points passed train gates.** See
research/results/phase3_train_families.md and the ledger for per-point
records. Not promoted to validation; look budget intact.
