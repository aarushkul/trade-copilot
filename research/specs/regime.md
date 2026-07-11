# Spec: regime — trend/range day-type layer (family a)

**Status:** DRAFT — grid frozen at first ledger registration.
**Kind:** conditioning layer, not a trade rule. Other families consume its output.

## Hypothesis (falsifiable)
Trend days and range days are distinguishable EARLY in the session from causal
features (noise-band breach time/persistence, opening drive size, gap size,
relative cumulative volume, opening-range width), and the two detected classes
have materially different forward drift-to-close. If detected classes do not
separate forward drift with bootstrap-t ≥ 2, the layer is dead and dependent
families run unconditioned.

## Labels (computed on full sessions, used ONLY as study targets, never as features)
trend_day := |RTH close − RTH open| ≥ 0.65 × RTH range AND RTH range ≥ 1.2 × 14-day median range.

## Candidate online detectors (all causal, decision at minute m of the session)
- noise-band breach: price beyond band for ≥ k consecutive minutes by minute m
  (k ∈ {3, 5, 10}; m ∈ {30, 60, 90})
- opening drive: |move from open| in band-half-width units at m ∈ {15, 30, 60}
  (threshold ∈ {0.75, 1.0, 1.5})
- gap context: |open − PDC| in ATR units (threshold ∈ {1, 2}) as a prior
- relative cumulative volume at m vs 14-day same-minute average (≥ {1.2, 1.5})

## Freeze gate (pre-registered)
Detected-trend vs detected-range separate forward drift-to-close with
bootstrap-t ≥ 2; each class covers ≥ 20% of sessions; sign and rough magnitude
stable across 2023 / 2024 / 2025 sub-periods. Frozen spec committed before any
dependent family is graded.

## Expected output
A `regime_at(session, minute)` feature ∈ {unknown, trend_up, trend_down, range}
added to the feature store (FEATURE_VERSION bump), plus a frozen-parameters
section appended to this file.
