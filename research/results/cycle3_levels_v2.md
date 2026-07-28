# Cycle 3 — levels_v2 verdict (2026-07-28)

Run `r-20260728-234331-0ae1598b`, 576 grid points on the full 2019–2026
train corpus, registered before evaluation (spec: research/specs/levels_v2.md,
commit b9f8d10). **0/576 passed the pre-registered train gates. Family
CLOSED for cycle 3 under its pre-committed readings.**

## What the widened grid actually revealed

The widening worked mechanically — event count scaled exactly as intended
(median n by approach floor: 2.5× → 638, 5.0× → 299, 10× → 51; max 2,857)
— and the result is the most informative negative of the program so far:

**44 grid points cleared PF ≥ 1.25 AND n ≥ 150 AND bootstrap-t ≥ 2, and
every single one failed the top-10-concentration gate** (top10 share of
net: 73%–120% vs < 40% required; several also missed months-positive).
A share above 100% means the ten best trades exceed the entire net profit
— the remaining hundreds of trades sum to a loss. Stress-slippage was
never the killer (survives at 1.4+); the plateau stage was never reached.

Representative points (full list in the ledger):

| pf | n | t | months+ | top10 | params |
|---|---|---|---|---|---|
| 1.55 | 185 | 2.7 | 64% | 78% | app 5, daily, break25, tn2, w1 |
| 1.47 | 307 | 3.1 | 68% | 83% | app 10, weekly, break25, tn2, rth |
| 1.43 | 365 | 3.2 | 64% | 89% | app 10, round, break25, tn2, rth |
| 1.44 | 293 | 2.6 | 57% | 120% | app 10, full, break50, tn2, rth |

Meanwhile the highest-PF points (PF 2.26–2.40, t 2.5–3.0) sit at n=51–59
— the v1 profile — failing only n ≥ 150.

## Structural read (recorded for the program)

The two failure modes are the same fact seen from both ends: **levels-break
P&L is outlier capture, not a per-event edge.** At high approach floors the
events are rare and the wins huge; widening the universe multiplies events
but the added trades contribute ~nothing — the profit still lives in the
same handful of trend-day monsters riding on a breakeven-to-negative base.
The bootstrap-t (2.5–3.2) is fat-tail-inflated and cannot honestly
distinguish "edge" from "a few lucky outliers across seven years"; the
concentration gate exists precisely because fb45 and the 07-09 fvg corner
had this profile in-sample and were fitted air out-of-sample.

**This downgrades the standing levels earmark.** The cycle-1b "revisit
mid-2027 when events double" note assumed scarcity was the only problem.
It is not: more tape would likely add more flat base and a few more
outliers. Any future levels revival must explain, in the spec, why its
event definition would concentrate P&L less — not just accumulate more n.

The advisory levels-break banner in the live app (context, never a call)
is unaffected: it makes no expectancy claim.

## Bookkeeping

- Program totals after this run: 2,168 registered evaluations, 0 survivors.
- All validation looks (2/family) and the single holdout look remain
  unspent. levels_v2 spent nothing.
- Next per the cycle-3 slate: gap (running), compression (running),
  cross-market ES→NQ, exit-structure.
