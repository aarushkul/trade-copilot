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

## RESULT — 2026-07-11, train (run r-20260711-200316-7e7648e4)

**No bucket × direction cell has positive expectancy.** Every significant
cell is significantly negative; unconditional canonical brackets lose in all
13 buckets both directions (752 sessions, ~287k RTH bars). Regime layer had
already failed, so no regime conditioning was applied.

Structure that does exist (all in the "where it's worst" direction):
- 09:30–10:00 is the worst unconditional bucket both ways (t ≤ −2.5 all arms).
- Shorts are uniformly bad (−0.03..−0.12 R; 2023–2025 up-drift), worst
  11:00–14:30 and 15:30.
- Longs are least bad midday: 11:30–14:00 at 2R sits ≈ 0 (t −0.5..+0.2);
  worst at 15:00 (−0.104/−0.127, t ≤ −3.6).

Per the pre-registered fallback: families run **full-RTH windows by
default**; the two candidate alternates below are recorded now, before any
family registers, and live inside family grids:
- tod-window-1 = 11:00–14:00 ET (midday; least unconditional drag)
- tod-window-2 = 10:30–15:00 ET (ex-open/ex-close)
