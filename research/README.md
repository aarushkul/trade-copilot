# Signal Research Protocol — Pre-Registration

This document is the binding contract for the signal redesign begun 2026-07-10.
It is committed BEFORE any evaluation runs; git history is the timestamp.
Results obtained outside this protocol do not count, no matter how good they look.

**Why this exists:** the previous engine measured PF 1.41 on its 25 tuning
sessions and PF 0.87 across 743 out-of-sample trades (188 unseen sessions,
Jun 2025–May 2026). The in-sample edge was fitted air. The failure was
process, not luck; this protocol is the corrected process.

## Objective

Find intraday MNQ signal rules/models with real positive expectancy net of
costs (commission $0.74/side, 1 tick slippage/market fill), robust across
regimes, deliverable as advisory calls in the existing engine.
**The success criterion is a correct verdict — "no edge exists at these
costs" is an acceptable, pre-registered outcome.**

## Splits (as code: app/research/splits.py — the only sanctioned data door)

| Split | session_date range | Contents | Access |
|---|---|---|---|
| TRAIN | 2023-01-01 .. 2025-12-10 | 2023–2025 Databento pull + oos_MNQU5/Z5 | unlimited, every grid ledger-registered |
| VALIDATION | 2025-12-11 .. 2026-05-26 | oos_MNQH6/M6 (~119 sessions) | ≤ 2 looks per family, ledger-enforced |
| HOLDOUT | 2026-05-27 .. forward | Schwab tape + walk-forward + live accumulation | exactly 1 look, assembled final system only |

Roll-boundary sessions (bars from two contracts) are flagged and excluded by
default. **Contamination acknowledgment:** family-level aggregates of the OLD
engine on H6/M6 were observed once (2026-07-09) and old trade dumps exist in
scratchpads; validation is therefore lightly bruised — acceptable for gating
NEW families; holdout + paper are the real arbiters. Old dumps must not be
consulted during research.

## Ledger (app/research/ledger.py → research/ledger.jsonl, committed)

- A **registration** record (family, spec_id, spec hash, full params grid,
  split, data fingerprint, git sha) is written and fsynced BEFORE results are
  computed. Every result record references its registration.
- Validation/holdout registrations consume the look budget; exhaustion raises.
- A tweaked grid/spec/fill-model/feature-version is a NEW registration.
- Specs live in research/specs/ and are committed before their first
  registration; the grid frozen at registration time is what counts.

## Fill & cost model `sim-1` (versioned; changing it bumps the version)

- Rules evaluate on **closed 1m bars**; orders act from the **next** bar.
- Market entries: next bar open ± 1 tick slippage against you. Limit/stop
  entries and limit targets require **1-tick trade-through** (touch ≠ fill).
- Intra-bar path: up bar O→L→H→C, down bar O→H→L→C (same as replay/powell).
- **Ambiguity rule: if a bar's range contains both stop and target, score STOP.**
- Stops and time exits pay slippage; friction 2 × $0.74 per contract round trip.
- Force-flat 15:59 ET; no entries 16:00–18:00; single bracket, 1 contract
  (the live T1/T2 runner is integration-phase scope).

## Gates (pre-registered; each stage can only shrink the survivor set)

| Gate | Criteria |
|---|---|
| Train advance | PF ≥ 1.25 AND n ≥ 150 AND ≥ 60% of calendar months positive AND top-10-trade share of net < 40% AND session-block bootstrap-t ≥ 2 (10k resamples) AND PF > 1.0 at 1.5× slippage AND plateau rule: median PF of ±1 grid neighbors ≥ 1.15 |
| Validation | PF ≥ 1.15 AND expectancy ≥ $4/trade net. ≤ 2 looks/family; the 2nd only for a pre-registered contingency, justified in the ledger |
| Holdout | PF ≥ 1.1, assembled final system, full-engine replay, ONE look |
| Paper (≥ 15 sessions) | signal rate within [0.5×, 2×] of backtest; realized expectancy within 1 bootstrap-σ; no behavioral divergence (entries at times/regimes the backtest wouldn't take) |

**Winrate is never a selection criterion at any stage** (measured 2026-07-07:
a 93.7%-winrate bracket lost $3.1k — winrate-optimizing selects for ruin).
It is recorded for diagnostics. A style preference (e.g. preferring the
higher-winrate of two survivors) may be applied only among validated survivors.
Selection metric within a family: expectancy in R, subject to all gates.
Carry at most the top-2 **non-adjacent** grid survivors per family to validation.

## Harness verification (all must pass before Phase 2 begins)

1. Golden deterministic sim tests: exact fills/costs on hand-built tapes.
2. Anti-lookahead: random (session, t) feature rebuilds from bars[:t+1] must
   be bit-equal to the cached matrix.
3. `fwd_*` firewall: rule predicates may not reference forward columns.
4. Cost arithmetic cross-checked to the cent vs app/journal/journal.py.
5. Research-sim vs replay.py parity on a known segment + a golden parity tape.
6. Placebo per finalist: entries shifted +5..+30 random minutes must collapse
   expectancy toward cost drag; a profitable placebo indicts the harness.
7. Data pull integrity: CME calendar counts, timestamp monotonicity, roll
   continuity vs neighbor contract, spot-check vs existing U5 file.

## Failure honesty

If no family survives validation (a live possibility — the old engine's OOS
base rate says retail 1m MNQ edges after costs are rare): no live signal
trading; Trade Copilot remains a discipline/journal/levels tool; the
infrastructure and data remain for future regimes; the verdict is recorded
here and in the ledger.

## Post-deployment learning loop (only if all gates pass)

Monthly: append new sessions → rebuild features → refit/re-grade on the
expanding train window → the refreshed config replaces production ONLY if it
re-passes validation-gate criteria on the newest ~20 unseen sessions;
otherwise production keeps the old config. Live journal decay monitor:
live expectancy below the backtest p10 auto-flags a re-measure. Every cycle
is ledger-logged. "Learns as it gets more data" — with a leash.

---

## CYCLE 1 VERDICT — 2026-07-11

Executed Phases 0-3 in full. Regime layer: dead (26/26 detectors failed the
freeze gate). Time-of-day: no positive bucket exists for unconditional
canonical brackets. Rule families + ML: **0 of 760 registered train
evaluations passed the pre-registered train gates** (best near-miss:
levels-break, PF 1.84 at n=75 — too rare and too concentrated to trust).
The ML track's ten-fold walk-forward peaked at PF 0.97 — below breakeven.

Per the failure-honesty clause: no candidate advances; the holdout look and
all validation looks remain unspent; **no live signal-trading from this
cycle**. Details: research/results/phase2_train_studies.md and
phase3_train_families.md. The next legitimate move is a future cycle with
either (a) materially new hypotheses registered before evaluation, or
(b) meaningfully more data (the levels-break n-gate failure becomes testable
around double the current event count).

## CYCLE 1b — train extension to contract launch (registered 2026-07-11, before evaluation)

MNQ launched 2019-05-06; the cycle-1 corpus arbitrarily started 2023-01-01.
Cycle 1b pulls 2019-05-06 → 2022-12-31 (16 contract windows, $4.69 of free
credits) and folds it into TRAIN — splits.py already maps pre-2023 session
dates to train, and older data cannot contaminate the untouched validation/
holdout windows. Nothing else changes: same specs, same frozen grids, same
gates, same sim-1. Every family + the ML track gets ONE new train
registration on the extended corpus (fingerprint distinguishes it in the
ledger). Motivation, stated before results: the cycle-1 near-misses failed
dominantly on n >= 150 and concentration; doubling the event count is the
pre-registered honest way to test whether they are patterns or dust.
Survivors, if any, resume Phase 4 under the untouched look budgets.
This section was written after the backfill was ordered but BEFORE any
feature build or grid evaluation on the extended corpus.

Cycle 1b data provenance notes: backfill ran 2026-07-11, $4.69 + $0.37
repair (free credits). The range boundary initially truncated
oos_MNQH3.json to Dec-2022-only; re-pulled the full H3 ownership window
(2022-12-09..2023-03-09, 63 sessions) the same day, before any store
rebuild or evaluation. The pull script now refuses to overwrite existing
files. Databento degraded-quality days in the backfill range, recorded:
2020-02-27/28, 2020-06-30, 2020-07-01, 2021-12-05, 2022-01-02.

**Cycle 1b verdict (2026-07-11, same day):** 0/760 on the extended corpus.
The cycle-1 vwap/trend near-misses collapsed on 2019-2022 data (the gates
were correctly calibrated); levels-break persisted (PF 2.17, t 2.9, n 68 —
fails only n >= 150) but is structurally too rare to trade; ML stayed
sub-breakeven at 124k rows/fold. Combined cycles 1+1b: 1,520 registered
evaluations, zero survivors. Phases 4-7 remain gated shut; all validation
looks and the holdout look are unspent.

**Cycle 2 verdict (2026-07-12):** orderflow via 1s tick-rule proxy — the
pre-registered proxy-credibility gate FAILED (0.706 < 0.8), so the 0/72
grid result is scoped "proxy too weak", not "order flow dead". True-flow
decode verified (+0.686 delta-return corr). A full-fidelity test needs
~$122/yr of NQ trades data (~$62 credits remain) — a user spending
decision. Program totals: 1,592 registered evaluations, zero survivors,
all look budgets intact.

## CYCLE 3 — new-hypothesis slate (registered 2026-07-28, running)

User mandate 2026-07-28: continuous autonomous research under this
protocol; authorities granted for autonomous data spend (≤ remaining
credits), immediate validation-look spend on a genuine train pass, and
auto paper-tracking on a validation pass. Holdout still requires explicit
user sign-off. Slate: levels_v2, gap, compression, cross-market ES→NQ,
exit-structure. Specs in research/specs/, each committed before its
registration.

**levels_v2 verdict (2026-07-28): 0/576, family CLOSED** — the widened
universe scaled n exactly as designed (median 638 events at the 2.5×
approach floor), and 44 points cleared PF/n/t simultaneously — but every
one failed top-10 concentration (73–120% of net in ten trades). Levels
P&L is outlier capture on a flat base, not a per-event edge; the
"revisit with more data" earmark is downgraded accordingly. Details:
research/results/cycle3_levels_v2.md.

**gap verdict (2026-07-28): 0/288, family CLOSED** (first run VOID for an
implementation fault — n=0 everywhere, documented in the spec; the fixed
identical grid is the counting run). Big-gap continuation carries PF
1.27–1.32 at t≈3 on n=661–724 but fails months-positive and top-10
concentration: gap-and-go is a trend-day subsample, not a daily edge.

**compression verdict (2026-07-28): 0/288, family CLOSED** — best PF 1.10
at t 0.7; coil breakouts are breakeven noise after costs.

**Cycle-3 meta-finding:** MNQ 1m price patterns net of costs = breakeven
base + rare trend-day outliers, measured now across four event
archetypes. Remaining slate: cross-market ES→NQ, then a trend-day-harvest
exit-structure spec (sim version bump for trailing exits), each
registered blind. Details: research/results/cycle3_gap_compression.md.

**xmkt verdict (2026-07-29): 0/64, family CLOSED (scoped ≥1m)** — ES
train corpus pulled under the registration ($8.51, fence physical:
validation-window ES never pulled). Best PF 0.99 at t −0.1; ES→NQ
extreme-divergence is fully priced at 1m, consistent with the cycle-2
flow-horizon null. Details: research/results/cycle3_xmkt.md.

## CYCLE 4 — user re-mandate 2026-07-28 ~21:30 ET (new-information slate)

Slate: event_day → vol_regime (VX skipped, cost cap; ES-RV fallback) →
overnight → daily_swing (research-only). Same protocol; 2026-07-28
authorities carried over.

**event_day verdict (2026-07-29): 0/144, CLOSED** — cpi_nfp follow PF
1.9–2.0 but n=63–80 (thin early pre-markets halve events), t < 2,
months + top10 fail. **vol_regime verdict (2026-07-29): 0/24, CLOSED,
thesis INVERTED** — best point is the low-vol falsification arm (PF
1.26, n=828, t 2.1, still concentration-sick); per the double-kill
pre-commitment the trend_harvest revival dies with it. Details:
research/results/cycle4_event_vol.md.

**trend_harvest verdict (2026-07-29): 0/288, family CLOSED — CYCLE 3
TERMINAL.** First sim-1.1 (trailing exits) family. Best point PF 1.20 on
n=1,692 (t 2.5) is the only genuine broad drift ever measured here — and
its top-10 share is 407% with 55% of months negative: trails AMPLIFY the
outlier structure instead of spreading it. The slate is exhausted.
Program lifetime: 21 pre-registered runs, 3,477 evaluated
configurations, zero survivors; all validation looks and the holdout
look UNSPENT, reserved for a future cycle with a genuinely new
information source. Full terminal report:
research/results/cycle3_trend_harvest_terminal.md.
