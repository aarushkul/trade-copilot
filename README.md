# Trade Copilot — Real-Time MNQ Signal Advisor

A local, advisory-only day-trading copilot for **MNQ (Micro Nasdaq-100
futures)**. It streams real-time CME data through Schwab's free Trader API,
runs a rule-based confluence engine (VWAP, opening range, key levels, EMAs,
volume, patterns), and shows live **LONG / SHORT / STAND ASIDE** calls — with
entry, stop, targets, contract count, and plain-English reasoning — on a
dashboard you keep open next to NinjaTrader Web.

**You** click the buttons in NinjaTrader. This never places trades.

Dashboard

## Quick start

**Easiest (Mac):** double-click `Start Trade Copilot.command` in Finder.
It opens Terminal, starts the engine, and opens [http://127.0.0.1:8000](http://127.0.0.1:8000) in your
browser. Click **Stop** on the dashboard when you're done (or press Ctrl+C in
Terminal).

From the terminal:

```bash
cd ~/Projects/trade-copilot
./start.sh
```

Manual flags if you prefer:

```bash
.venv/bin/python run.py              # demo mode, simulated feed
.venv/bin/python run.py --feed schwab  # live Schwab only (see SETUP.md)
.venv/bin/python run.py --feed auto    # Schwab if configured, else demo
```

Dashboard: **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

New machine? `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`

## How it decides

Every 15 seconds the engine evaluates setup modules that each cast weighted
votes (opening-range breakout, VWAP reclaim/reject and band fades, key-level
reactions, EMA pullbacks, noise-band momentum, multi-timeframe structure,
RSI divergence, candlestick patterns). A call fires only when:

- aligned votes reach the **A-grade** bar (score ≥ 4.75 with trend alignment
and volume confirmation — B-grade confluence is context, never a call),
- one of the two **trigger** setups is present — EMA pullback in trend or
opening-range breakout. Everything else (BOS, CHoCH, sweeps, VWAP plays,
level reactions, patterns) only adds or removes conviction,
- volume confirms breakout-type entries,
- the chop filter, session windows, cooldown, **daily cap (2 calls max)**,
and circuit breaker all allow it.

**Selectivity mode (2026-07-12).** The research program measured a
0.03–0.13 R cost toll on *every* entry across 1,680 sessions, with the
worst buckets at 09:30–10:00 and after 15:00 — so the engine now only
looks between 10:00 and 15:00 ET, fires A-grade only, and stops after two
calls. Zero-signal days are a feature, not a malfunction: on the 25-session
reference tape this configuration fires ~0.3 calls/day (was ~4.8).
HTF break-of-structure was demoted from trigger to confluence after the
188-session out-of-sample test showed it carried the fitted edge
(−$1,792 OOS). The old 1m structure triggers (CHoCH/sweep churn) remain
confluence-only.
Price beyond the session's time-of-day **noise band** (average move from open
at this minute, trailing 14 sessions) marks a trend day: band-fade signals are
suppressed there, and the band is drawn on the chart.

An **abnormal-move banner** flags any 1m bar ≥2× ATR and ≥2× volume (e.g. the
2026-07-09 10:15 ET 93-pt flush). It is advisory only — replays over 25 real
sessions showed that chasing such bars loses money (PF 0.47), so the engine
deliberately stands aside and the banner says so instead of trading it.

A **levels-break banner** marks the one pattern that persisted across the
2019–2026 research corpus (first touch of a prior-day/overnight level after
a long approach, then a 1m close through — PF 2.17, bootstrap-t 2.9). At
~10 events/year it is statistically unvalidatable and therefore **never a
call** — it appears as context for the discretionary trader only.

**Risk per call** — A-grade risks up to $150, B-grade $100. Contracts =
risk budget ÷ (stop distance × $2/pt), capped at 2. Stop too wide → no call.
Two stop-outs in a day → circuit breaker locks the engine until tomorrow.

**Runner logic** — with 2 contracts, half banks at target 1 (1R), the runner
goes for 2R with the stop moved to breakeven.

## The journal keeps you honest

Every signal is tracked against the live tape as if taken: stopped, target
hit, or flat-exit on timeout. The dashboard shows today's and all-time win
rate, P&L, and average R by setup type. Signals are tagged `live` or `sim`
by feed source; stats and circuit-breaker seeding use live rows only, so a
demo session can never flatter the record. **Paper-trust it before you
real-trust it.**

At the end of each week run the edge report before changing anything:

```bash
.venv/bin/python scripts/edge_report.py        # last 7 days, live only
```

It slices the week by setup, grade, hour and session (with sample-size
flags), shows how much of the P&L came from the best 10% of trades, and
prints the "scalper tax" — what banking $50 whenever it was on the table
would have done to the week.

## Backtest / tuning

```bash
# real MNQ 1m bars (fetch via Schwab price history into data/history/)
.venv/bin/python -m app.backtest.replay --file data/history/mnq_1m.json
# isolate one setup's edge / sweep parameters
.venv/bin/python -m app.backtest.replay --file data/history/mnq_1m.json \
    --measure --triggers pullback --fire-b 4.0 --t2 3 --max-age 90
.venv/bin/python -m app.backtest.replay --days 10 --seed 7   # synthetic tape
.venv/bin/python -m pytest tests/ -q
```

The replay harness runs the exact live engine over historical 1m bars, with
session-aware warmup and stats **net of commission and slippage** (see
`commission_per_side` / `slippage_ticks` in settings). `--measure` disables
the circuit breaker so one bad morning doesn't truncate the sample;
`--triggers` restricts which setups may fire; `--bracket T,S` overrides the
bracket (useful for demonstrating why win-rate alone is meaningless).
Synthetic tape validates mechanics only — tune against real MNQ data.

## Layout

```
run.py                  entry point
app/config.py           settings (persisted to data/settings.json)
app/feed/               schwab_feed, sim_feed, multi-timeframe bars
app/indicators/         VWAP+bands, EMA, RSI/divergence, ATR, volume, patterns
app/engine/             setups, confluence engine, risk, sessions, chop filter
app/journal/            SQLite journal + outcome tracking
app/server/             FastAPI + WebSocket + dashboard (static/)
app/backtest/           replay harness + standalone strategy backtests
scripts/schwab_login.py one-time OAuth
scripts/edge_report.py  weekly journal edge report (live-only by default)
```



## Honest expectations

This is a disciplined second set of eyes that enforces confluence, sizing,
and "don't trade chop" — where most discretionary traders bleed. It is not a
money printer. **The 2026-07 research program (1,592 pre-registered
evaluations over 2019–2026 data — rule families, machine learning, order
flow) found no signal configuration with provable positive expectancy at
retail costs; see `HANDOFF.md` and `research/`.** The signals are therefore
tuned for maximum selectivity and minimum toll, and the app's proven value
is the discipline layer: sizing, circuit breaker, journal, and stand-aside. On the 25 real sessions used for tuning (May–Jul 2026, net of
costs) the current configuration measured ~53% win rate, ~$3.7 expectancy per
signal and profit factor ~1.09, stable across both halves of the sample —
thin, and not statistically distinguishable from breakeven at that sample
size. No configuration tested reached a high win rate with positive
expectancy; a 93.7%-win-rate bracket variant *lost* $3.1k on the same tape.
Win rate is a design parameter, not a quality metric — expectancy is the
metric. Exit shape was measured the same way: fixed scalp brackets
(PF 0.31–0.50) and fewer-but-bigger variants (higher fire threshold, 6R
runners) all did worse than the default half-at-1R / runner-to-2R
management, so trade the calls as given — don't bank $50 early and don't
hold out for the home run. Validate stats on paper before sizing up, and remember $150 risk on
a $1,200 account is aggressive; the circuit breaker exists for a reason.