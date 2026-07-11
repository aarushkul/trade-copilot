# Spec: orb — regime/volume-conditioned opening-range breakout (family c)

**Status:** DRAFT — grid frozen at first ledger registration.

## Hypothesis (falsifiable)
Unconditioned ORB is breakeven-at-best after costs (the old engine's orb
measured PF 0.25–1.01 OOS); conditioned on elevated volume and trend-friendly
context (gap agreement / early trend regime), first breaks of the opening
range carry follow-through. External evidence: SSRN 4416622 (conditioned ORB
on QQQ/day-session).

## Entry (feature terms)
- OR length ∈ {5, 15, 30} min; first 1m CLOSE beyond OR high/low after OR completes
- freshness: entry only within {2, 6} points of the OR edge (ATR-scaled arm: {0.25, 0.5}·atr_5m)
- conditions (grid): rvol_1m ≥ {1.0, 1.5} at break; gap-agree ∈ {any, gap-side-only};
  regime ∈ {any, trend-only} (if frozen)
- window: breaks before {11:00, 12:00} only

## Exit
- stop: opposite OR edge OR {1.0, 1.5} × atr_5m, whichever nearer (clamped 5–45 pt)
- target: {1R, 2R} OR hold-to-close arm

## Grid ≈ 3·2·2·2·2·2·2·3 ≈ 288 → prune to ≤ 200 at freeze. Expected: 0–1 trades/session.

## Pre-registration addendum — 2026-07-11, before first registration
Regime layer FAILED (see regime.md): regime arm collapses to {any}. The
break-before-{11:00, 12:00} windows stand as specced (structural, not
tod-derived). tod study note: 09:30–10:00 has the worst unconditional drag,
so the volume/freshness conditions carry the whole burden of proof.

## RESULT — 2026-07-11, train (cycle 1)
**FAILED — 0 grid points passed train gates.** See
research/results/phase3_train_families.md and the ledger for per-point
records. Not promoted to validation; look budget intact.
