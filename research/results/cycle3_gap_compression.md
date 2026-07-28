# Cycle 3 — gap and compression verdicts (2026-07-28)

## gap — 0/288, family CLOSED

Runs: `r-20260728-234818-490b4b52` (VOID — implementation fault: the
open-bar test matched the 18:00 Globex session start, zero trades on all
288 points, zero information extracted; fixed and documented in the spec)
and `r-20260728-235311-490b4b52` (the counting run, identical frozen grid).

Best points, none passing:

| pf | n | t | months+ | failure | params |
|---|---|---|---|---|---|
| 1.32 | 661 | 3.1 | <60% | months, top10 | gmin 2.0 uncapped, GO, delay 15, 2R |
| 1.29 | 178 | 1.5 | <60% | months, top10, t | gmin 2.0 cap 4, FADE, delay 30, 2R |
| 1.27 | 724 | 2.8 | <60% | months, top10 | gmin 1.0 uncapped, GO, delay 15, 2R |

Directional structure matches the lore — big gaps continue (GO beats FADE
grid-wide) — but the P&L is month-lumpy and top-10-concentrated: gap-and-go
profits are a trend-day subsample, not a daily edge. Per the pre-committed
reading: CLOSED, no re-grid, the fade-vs-go asymmetry recorded here only.

## compression — 0/288, family CLOSED

Run `r-20260728-235007-b1010492`. Not even close: best PF 1.10 at t 0.7
(NR7-conditioned, m=20, c=3.0, w2). Coil breakouts on MNQ 1m are breakeven
noise after costs at every conditioning tried. CLOSED per pre-commitment.

## The cycle-3 meta-finding (recorded before any further specs)

Across levels_v2 (44 PF/n/t-clearing points, all top10-concentrated
73–120%) and gap (PF 1.27–1.32 at t≈3, months+top10 fail), the SAME
structure keeps appearing: **MNQ 1m price patterns net of costs are a
breakeven base plus rare trend-day outliers.** The profit is real but it
lives in a small number of days, which is exactly what the concentration
gate is built to reject as an every-day signal engine.

Implication for the remaining slate: the honest final hypothesis is not
another per-event edge but a trend-day harvest structure — entries that
only matter on the days that pay everyone, with exits engineered to spread
tail capture across many such days (trailing exits need a sim version
bump). Any such spec must be registered blind BEFORE further data
inspection, and must pass the same concentration gate — spread across
~50–80 trend legs in 7 years, not 10.

## Bookkeeping

- Program totals: 3,032 registered evaluations (288 of them the void
  gap run), zero survivors. All validation looks and the holdout look
  remain unspent.
- Remaining slate: cross-market ES→NQ (data pull authorized), then the
  trend-harvest / exit-structure registration.
