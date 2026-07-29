# Cycle 3 — trend_harvest verdict, and the cycle-3 TERMINAL REPORT (2026-07-29)

## trend_harvest — 0/288, family CLOSED; the slate is exhausted

Run `r-20260729-010822-d88af161`, 288 points, first family under sim-1.1
(uncapped ATR trailing exits, golden-tested). **0/288 passed.**

The best point is the most informative single result of the program:

- N=30 breakout, no filter, 4×ATR trail (widest tried), cap 1/side, rth:
  **PF 1.20, n=1,692, expectancy $6.31/trade, bootstrap-t 2.5** —
  a genuine, broad, seven-year positive drift, the only one ever measured
  here. And: **months-positive 55%, top-10 share 407%.** Ten trades are
  four TIMES the entire net; the base of ~1,680 trades is deeply
  negative; nearly half of all months lose.

Per the spec's pre-committed reading: exit engineering does NOT spread
the outlier structure — it magnifies it (the trail turns the same few
trend days into monsters while everything else bleeds). The trades exist,
the drift is real, and it is structurally a lottery-ticket distribution,
the exact opposite of an every-week income stream. No re-grid; wider
trails would be a cycle-4 hypothesis and the gradient toward them is
recorded here for honesty, with the prior that concentration worsens.

## CYCLE 3 TERMINAL REPORT

Slate executed in full, every spec registered blind before evaluation:

| family | grid | verdict | one-line cause |
|---|---|---|---|
| levels_v2 | 576 | 0/576 CLOSED | 44 PF/n/t-clearing points, all top10-concentrated 73–120% |
| gap | 288 (+288 void) | 0/288 CLOSED | big-gap GO PF 1.32/t 3.1 but month-lumpy, top10-concentrated |
| compression | 288 | 0/288 CLOSED | PF ≤ 1.10, breakeven noise |
| xmkt (ES→NQ) | 64 | 0/64 CLOSED (≥1m) | PF 0.96–0.99 everywhere; efficiently coupled |
| trend_harvest | 288 | 0/288 CLOSED | drift real (PF 1.20, t 2.5) but top10 = 407% |

Cycle 3: 1,792 grid evaluations (288 void), one fill-model extension
(sim-1.1), one new data asset (ES 1m train corpus, $8.51). Program
lifetime: **21 pre-registered runs, 3,477 evaluated configurations, zero
survivors of the train gates. All validation looks (2/family) and the
single holdout look remain UNSPENT.**

## The three measured truths (cycle 3's contribution in bold)

1. Per-event 1m MNQ edges do not clear retail costs (cycles 1–2; re-confirmed).
2. **What profit exists concentrates in rare trend-day outliers — now
   measured across five independent event archetypes.**
3. **Exit engineering cannot spread that concentration; it amplifies it.**
4. (Standing) Flow and cross-market information are fully priced at ≥1m;
   sub-minute remains untested at our cost ceiling.

## What this means, stated plainly

- An advisory 1m signal engine on MNQ at these costs has no gate-passing
  configuration in 3,477 tries spanning 2019–2025. That is a measured
  property of the market at this timescale and cost structure, not a
  failure of effort or intelligence.
- The weekly-income framing ($500/wk) is structurally incompatible with
  the one real drift found: intraday trend capture pays like a lottery
  (55% losing months), not like a salary — and it is sub-gate anyway.
- The look budgets survive intact. They are reserved for a future cycle
  with a genuinely NEW information source (different timescale, different
  data), not for re-mining this corpus.
- The app remains what the evidence says it is: a discipline layer —
  sizing, breaker, journal, levels/VWAP context, selectivity mode.
  REAL MONEY stays OFF for signal-following.
