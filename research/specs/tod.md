# Spec: tod — time-of-day expectancy structure (family e)

**Status:** DRAFT — grid frozen at first ledger registration.
**Kind:** descriptive study, not a trade rule. Output feeds other specs' windows.

## Hypothesis (falsifiable)
Net-of-cost expectancy of canonical brackets is not uniform across the session:
after costs, most 30-minute buckets are unprofitable in both directions, and
any edge concentrates in a small number of buckets (expected: post-open
09:35–11:00 and afternoon trend 13:30–15:30, per prior literature). If no
bucket × direction × regime cell shows |bootstrap-t| ≥ 2, time-of-day carries
no structure and families run with the full-RTH window only.

## Method
For every RTH 1m bar in train: enter long and short with the canonical
brackets (stop 1.0 × atr_5m, target ∈ {1R, 2R}, horizon 60 min), sim-1 fills.
Aggregate expectancy by 30-min bucket × direction × regime (if frozen).
Purely descriptive: no selection happens here.

## Output
≤ 3 pre-registered candidate session windows PER FAMILY, appended to each
family spec before that family's first registration. Window choice then lives
inside the family grid — never post-hoc.
