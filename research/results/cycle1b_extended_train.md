# Cycle 1b results — same frozen grids, train extended to 2019 (contract launch)

Date: 2026-07-11. Corpus: 1,680 usable train sessions (2019-05 → 2025-12-10;
was 750), validation/holdout untouched. Runs `r-20260711-210357` (vwap),
`-210604` (orb), `-210815` (trend_continuation), `-211018` (levels), plus the
ml run — all registered before evaluation. Data cost: $5.06 of free credits.

## Verdict: ZERO survivors, again — 0/760

| family | cycle-1 best (750 sessions) | cycle-1b best (1,680 sessions) | reading |
|---|---|---|---|
| vwap_reversion | PF 1.33, n=190 | PF 1.12, n=386 | **collapsed** — period noise |
| orb | PF 1.14 | PF 1.19, t=1.3 | flat, dead |
| trend_continuation | PF 1.64, n=57 | PF 1.29, n=127 | **collapsed** |
| levels | PF 1.84, n=75, t=2.6 | **PF 2.17, n=68, t=2.9** | persistent, still too rare |
| ml | PF 0.97 | PF 0.98 (124k rows/fold) | sub-breakeven at any scale |

## The two important findings

**1. The gates were right.** The vwap and trend-continuation near-misses that
looked tempting on 2023-2025 regressed hard when 2019-2022 (COVID crash,
2021 melt-up, 2022 bear) was added. Had cycle 1 promoted them, validation
looks would have been burned on noise. This is the system working.

**2. levels-break is a real-looking pattern that cannot carry a strategy.**
Break-through continuation after a first touch approached from >= 5 x atr_1m
distance holds PF 1.5-2.2 with bootstrap-t >= 2 on several non-adjacent grid
points across SEVEN years and three market regimes. The best point
(hlc levels, 11:00-14:00 window) now fails exactly ONE gate: n >= 150 (it has
68 trades in 6.5 years ≈ 10/year). The wider variants that reach n=138 fail
on profit concentration instead. Structural read: the event is genuinely
scarce — reaching n=150 at this event rate needs ~8 more years of tape, or a
**wider event definition, which would be a new hypothesis and must be
pre-registered blind before anyone looks again**. No such run was performed.

## Consequences

- Phases 4-7 remain gated shut: no validation looks spent, holdout virgin.
- No live signal-trading. The app stays a discipline/journal layer.
- The learning loop (`scripts/research/retrain.py`) is the standing
  machinery: run it monthly (`--extend`) to accumulate fresh unseen
  sessions and reprint this status. Per the approved plan, its *scheduled*
  form activates only if a system ever deploys.
