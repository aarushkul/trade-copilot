# Trade Copilot — Project State & Handoff

Last updated: 2026-07-29 (cycle-3 terminal). This file is the single-page
context for anyone (human or AI) picking up the project. Deep details live
in `research/README.md` (binding protocol), `research/results/*.md`
(verdicts), `research/ledger.jsonl` (every registered evaluation), and the
auto-memory.

## What this project is

Advisory-only day-trading copilot for MNQ (Micro Nasdaq futures): Schwab
feed → 1m bars → signal engine → SQLite journal → FastAPI dashboard
(http://127.0.0.1:8000). It never places trades. User trades manually in
NinjaTrader with a ~$1,200 account. Start: `./start.sh` or the
`Start Trade Copilot.command` icon. Schwab refresh tokens die every ~7
days → `.venv/bin/python scripts/schwab_login.py` (interactive).

## The one-paragraph status

**No tradeable signal edge exists on MNQ 1m at retail costs — measured,
not suspected: 21 pre-registered runs, 3,477 evaluated configurations
(2019–2025, five cycles of families incl. ML, orderflow, cross-market ES,
and trailing-exit structures), zero passed the pre-registered train
gates.** The one genuine drift found (trend_harvest breakout + 4×ATR
trail: PF 1.20, n=1,692, t 2.5) is lottery-shaped — top-10 trades = 407%
of net, 55% of months negative — structurally incapable of weekly income.
All validation looks and the single holdout look are UNSPENT, reserved
for a future cycle with genuinely new information (different timescale or
data, not this corpus re-mined). The app's standing value is the
discipline layer: sizing, circuit breaker, journal, selectivity mode,
levels/VWAP context. REAL MONEY OFF for signal-following.

## Verdict timeline (all in research/results/ + ledger)

| date | what | verdict |
|---|---|---|
| 2026-07-10 | Old engine on 188 unseen Databento sessions | PF 0.87, −$4,103 → fitted air; real money off |
| 2026-07-11 | Cycle 1: regime/tod + 4 families + ML (750 sessions) | 0/760; regime dead 26/26 |
| 2026-07-11 | Cycle 1b: train extended to 2019 (1,680 sessions) | 0/760; near-misses collapsed |
| 2026-07-12 | Cycle 2: orderflow proxy + horizon study | 0/72 scoped "proxy weak"; flow priced within its minute at 1-60m |
| 2026-07-28 | Cycle 3: levels_v2 (widened universe) | 0/576; 44 PF/n/t-passers ALL top10-concentrated → levels = outlier capture |
| 2026-07-28 | Cycle 3: gap (first registration; 1 void run) | 0/288; big-gap GO PF 1.32/t 3.1 but month-lumpy + concentrated |
| 2026-07-28 | Cycle 3: compression (NR/coil) | 0/288; breakeven noise |
| 2026-07-29 | Cycle 3: xmkt ES→NQ divergence ($8.51 ES pull) | 0/64; PF ≤ 0.99 — coupled at 1m |
| 2026-07-29 | Cycle 3: trend_harvest (sim-1.1 trails) — TERMINAL | 0/288; drift real (PF 1.20/t 2.5) but top10 = 407% |

## The research protocol (binding, research/README.md)

- Splits as code (`app/research/splits.py`): TRAIN ≤ 2025-12-10,
  VALIDATION 2025-12-11→2026-05-26 (≤2 looks/family), HOLDOUT ≥ 2026-05-27
  (ONE look ever). Guarded loaders make split-crossing structurally hard.
- Ledger (`research/ledger.jsonl`): registration BEFORE results, always.
- Train gates: PF≥1.25, n≥150, ≥60% months positive, top-10-trade share
  <40%, session-bootstrap t≥2, PF>1.0 at 1.5× slippage, plateau rule.
- Winrate is recorded, NEVER selected on. Specs are committed blind before
  registration; a tweaked spec is a NEW registration.
- Fill models: sim-1 (brackets) and sim-1.1 (stop-only ATR trail ratchet,
  golden-tested) in `app/research/sim.py`.

## Data assets (data/ is gitignored; files immutable once pulled)

- MNQ 1m per-contract: `data/history/oos_MNQ*.json` — 2019-05-06 →
  2026-05-26 (Databento GLBX.MDP3, raw symbols, expiry−8d roll; NEVER
  continuous symbology). Schwab tape covers ≥ 2026-05-27.
- ES 1m per-contract TRAIN-ONLY: `data/history/xmkt_ES*.json` — 2019-05-06
  → 2025-12-10. Validation-window ES deliberately never pulled (fence).
- NQ flow proxy (2025) + one true-trades month: `data/history/flow_*`.
- Feature store v1: `data/research/features/v1/{split}.parquet`.
- Databento spend: ~$71 of ~$125 free credits (~$54 remain).

## Commands

```bash
.venv/bin/python -m pytest tests/ -q                 # full suite (105)
.venv/bin/python scripts/research/run_family.py --family <name>  # register+run
.venv/bin/python scripts/research/retrain.py --extend # monthly corpus refresh
.venv/bin/python scripts/edge_report.py              # weekly journal report
```

Families: regime, tod, vwap_reversion, orb, trend_continuation, levels,
levels_v2, gap, compression, xmkt, trend_harvest, ml, orderflow, ml_flow.
ALL CLOSED as of cycle-3 terminal.

## Standing decisions & guardrails

- **No live signal-following.** Nothing has ever passed Phase 3. The
  holdout look requires a validated survivor AND explicit user sign-off.
- Look budgets are pristine and reserved for genuinely NEW information
  (different timescale/data). Re-mining this corpus is forbidden —
  registered aggregates only.
- Levels earmark DOWNGRADED (2026-07-28): more data adds flat base plus
  a few more outliers; any revival spec must argue reduced concentration.
- Order flow ≥1m: CLOSED. Cross-market price structure ≥1m: CLOSED.
  Sub-minute: untested, cost-prohibitive (~$122/yr per instrument).
- The 2026-07-28 user authorities (auto data spend ≤ credits, auto
  validation look on train pass, auto paper on validation pass) were
  exercised within cycle 3 only; the cycle is over and the autonomous
  loop is STOPPED. A new cycle needs a new user conversation.
- Old scratchpad OOS dumps must never be mined; winner's-curse rules
  stand. `.env` holds SCHWAB_* + DATABENTO_API_KEY — never print values.
- The live app stays up as the discipline layer; don't kill it during
  research.

## User context

Aarush trades MNQ manually with ~$1,200; goal framing 2026-07-28 was
"+$500/week" — told honestly (measured): no validated edge does that at
this account size, and the one real drift found is structurally
lottery-shaped. User owns sizing/scaling decisions; the machine owns
signal/exit research under the protocol. Decisive framings that landed:
winrate ≠ expectancy, look budgets as one-shot resources, friction toll,
variance vs edge.

## Selectivity mode (2026-07-12, live config — unchanged)

a_grade_only=true, daily_signal_cap=2, entries 10:00–15:00 ET, triggers
{pullback, orb}, levels-break advisory banner (never a call), sizing and
breaker unchanged. Settings in data/settings.json. Measured: ~0.3
calls/day. Zero-signal days are expected and correct.
