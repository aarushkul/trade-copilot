# Spec: ml — learned pattern models (the "learns from data" track)

**Status:** DRAFT — grid frozen at first ledger registration.

## Hypothesis (falsifiable)
A regularized tabular model over the causal feature set predicts net-of-cost
forward bracket R well enough that the policy "enter when prediction > θ"
passes the same train gates as the rule families. If the model cannot beat
the best rule family under identical fills, gates, and look budgets, learned
patterns add nothing at this data scale.

## Data
- X: causal feature matrix (FEATURE_VERSION pinned in the registration),
  RTH rows, 5-minute row stride to cut autocorrelation
- y: fwd_net_r_{30,60}m for the canonical bracket (long and short as separate
  problems or signed-target arm — grid choice)
- **The fwd_* firewall applies: features and targets never mix.**

## Models & CV
- logistic regression baseline (must be run and reported first)
- HistGradientBoosting (classifier on sign / regressor on R — grid arm)
- expanding walk-forward by quarter over train (~10 folds),
  purge = forward horizon, embargo = 1 full session at fold edges
- pooled fold-OOS predictions → policy "enter when pred > θ",
  θ grid pre-registered {0.55, 0.6, 0.65, 0.7 quantile arms}, max 1 concurrent
  position, evaluated through sim-1 fills and the standard train gates

## Interpretability & artifacts
Permutation importance reported per fold; model artifacts frozen to
data/research/models/ with hashes in the ledger. Integration decision
(sklearn inference in-app vs tree export) deferred until a model survives.

## Post-deployment retraining (Phase 7)
Monthly refit on the expanding window; the refreshed model replaces production
only if it re-passes validation-gate criteria on the newest ~20 unseen
sessions; otherwise production keeps the prior model.

## RESULT — 2026-07-11, train (cycle 1)
**FAILED — 0 grid points passed train gates.** See
research/results/phase3_train_families.md and the ledger for per-point
records. Not promoted to validation; look budget intact.
