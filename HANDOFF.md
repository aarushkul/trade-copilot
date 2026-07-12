# Trade Copilot — Project State & Handoff

Last updated: 2026-07-12 (overnight). This file is the single-page context for
anyone (human or AI) picking up the project. Deep details live in
`research/README.md` (binding protocol), `research/results/*.md` (verdicts),
`research/ledger.jsonl` (every registered evaluation), and the auto-memory.

## What this project is

Advisory-only day-trading copilot for MNQ (Micro Nasdaq futures): Schwab
feed → 1m bars → signal engine → SQLite journal → FastAPI dashboard
(http://127.0.0.1:8000). It never places trades. User trades manually in
NinjaTrader with a ~$1,200 account. Start: `./start.sh` or the
`Start Trade Copilot.command` icon.

## The one-paragraph status

**The signal engine has no edge, and that is now proven, not suspected.**
The deployed engine measured PF 0.87 over 743 unseen-data trades (2026-07-10
verdict → REAL MONEY OFF). The ground-up redesign research program
(pre-registered protocol, cycles 1, 1b, 2) evaluated **1,592 registered
configurations** — four rule families, an ML track, regime/time-of-day
studies, and an order-flow family — across up to 1,680 training sessions
(2019→2025). **Zero passed the pre-registered train gates.** All validation
looks (2/family) and the single holdout look remain UNSPENT. No live
signal-following. The app's remaining value is the discipline layer:
position sizing, circuit breaker, journal, chop/stand-aside, levels/VWAP
context.

## Verdict timeline (all in research/results/ + ledger)

| date | what | verdict |
|---|---|---|
| 2026-07-10 | Old engine on 188 unseen Databento sessions | PF 0.87, −$4,103 → fitted air; real money off |
| 2026-07-11 | Cycle 1: regime + tod studies (train) | regime dead 26/26; no positive tod bucket |
| 2026-07-11 | Cycle 1: 4 rule families + ML (750 sessions) | 0/760 pass |
| 2026-07-11 | Cycle 1b: same grids, train extended to 2019 (1,680 sessions) | 0/760 pass; vwap/trend near-misses collapsed; levels-break persists (PF 2.17, t 2.9, n=68 — fails only n≥150); ML PF 0.98 |
| 2026-07-12 | Cycle 2: orderflow (NQ 1s tick-rule proxy, 2025) | 0/72; **proxy credibility gate FAILED (0.706 < 0.8)** → scoped "proxy too weak", NOT "order flow dead"; side decode verified (+0.686); full-fidelity test costs ~$122/yr vs ~$62 credits left |

## The research protocol (binding, research/README.md)

- Splits as code (`app/research/splits.py`): TRAIN ≤ 2025-12-10,
  VALIDATION 2025-12-11→2026-05-26 (≤2 looks/family), HOLDOUT ≥ 2026-05-27
  (ONE look ever). Guarded loaders make split-crossing structurally hard.
- Ledger (`research/ledger.jsonl`): registration BEFORE results, always.
- Train gates: PF≥1.25, n≥150, ≥60% months positive, top-10-trade share
  <40%, session-bootstrap t≥2, PF>1.0 at 1.5× slippage, plateau rule.
- Winrate is recorded, NEVER selected on (a 93.7%-WR config lost $3.1k).
- sim-1 fills: next-bar entry, 1-tick trade-through limits, both-in-bar =
  STOP, force-flat 15:59 ET, $0.74/side + 1 tick slip.
- **Iron rules:** never evaluate before registering; never peek at
  validation/holdout without consuming a ledger look; a wider/tweaked spec
  is a NEW registration written blind.

## Data assets (data/ is gitignored; files are immutable once pulled)

- MNQ 1m per-contract: `data/history/oos_MNQ*.json` — 2019-05-06 → 2026-05-26
  (Databento GLBX.MDP3, raw symbols, expiry−8d roll; NEVER continuous
  symbology — measured divergence). Schwab tape covers ≥ 2026-05-27.
- NQ flow proxy: `data/history/flow_NQ1s_2025.parquet` (per-minute tick-rule
  buy/sell from 1s bars, 2025 train year) + `flow_NQtrades_val.parquet`
  (one month of true aggressor trades for proxy validation).
- Feature store: `data/research/features/v1/{split}.parquet` (~52 causal
  cols, 2.49M rows); outcomes (fwd_* targets) and flow features in parallel
  trees. Rebuild: `scripts/research/build_features.py`, `build_flow.py`.
- Databento spend: ~$63 of ~$125 free credits (~$62 remain). Degraded-quality
  days listed in research/README.md.

## Commands

```bash
.venv/bin/python -m pytest tests/ -q                 # full suite
.venv/bin/python scripts/research/build_features.py  # features+outcomes+verify
.venv/bin/python scripts/research/build_flow.py      # flow store + proxy checks
.venv/bin/python scripts/research/run_family.py --family <name>   # register+run
.venv/bin/python scripts/research/retrain.py --extend # monthly learning loop
.venv/bin/python scripts/edge_report.py              # weekly journal report
```

Families: regime, tod, vwap_reversion, orb, trend_continuation, levels,
ml, orderflow, ml_flow.

## Standing decisions & guardrails

- **No live signal-following** until something passes train → validation →
  holdout → ≥15 paper sessions (Phases 4-6). Nothing has passed Phase 3.
- The single holdout look is the most precious asset. Do not spend it
  without a validated survivor and explicit user sign-off.
- Old scratchpad OOS trade dumps must never be mined for "surviving
  corners" — that re-commits winner's curse.
- Earmarked lead 1: levels-break (break-through continuation after a
  ≥5-10×atr_1m approach). Persistent across 7 years but ~10 events/yr.
  A wider-event levels-v2 spec is legitimate ONLY if written and
  registered before any further data peeking.
- Earmarked lead 2: order flow at FULL fidelity (true NQ trades,
  ~$122/yr) — the proxy failed its credibility gate, so the hypothesis is
  untested, not dead. Requires user-approved spend; staged rule in
  research/specs/orderflow.md applies.
- The live app (run.py, port 8000) stays up as the discipline layer; do
  not kill it during research work.
- `.env` holds SCHWAB_* + DATABENTO_API_KEY — never print values.

## User context

Aarush trades MNQ manually with ~$1,200; wants a profitable, learning
system ("AI is too powerful to not be able to be a good day trader") and
has been given the honest counter-evidence at each step. Prefers
measurements over opinions; approved the pre-registered protocol; the
decisive framings that landed: winrate ≠ expectancy, look budgets as
one-shot resources, friction toll per trade, variance vs edge (gambling).
