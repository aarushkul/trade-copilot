"""Backtest/replay harness: run the exact live engine over historical 1m bars.

Each 1m bar is expanded into 8 synthetic quotes tracing an O-H-L-C path so the
engine's 15s evaluation cadence, journal tracking, stops and targets all work
the same way they do live. Not an institutional backtester - a tuning tool.

Stats are net of commission + slippage (see Settings). Warmup is session-aware
so indicators, levels and the 14-session noise bands are all primed before the
first measured signal.

Usage:
    .venv/bin/python -m app.backtest.replay --file data/history/mnq_1m.json
    .venv/bin/python -m app.backtest.replay --file ... --triggers pullback
    .venv/bin/python -m app.backtest.replay --file ... --measure   # per-setup edge
    .venv/bin/python -m app.backtest.replay --days 10 --seed 7     # synthetic tape
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.config import Settings
from app.engine.engine import SignalEngine
from app.engine.session import session_date
from app.journal.journal import Journal
from app.models import Bar, Quote, Signal


def bar_to_quotes(bar: Bar) -> list[Quote]:
    """Expand a 1m bar into an O->H->L->C (or O->L->H->C) quote path."""
    up = bar.close >= bar.open
    path = ([bar.open, bar.low, bar.high, bar.close] if up
            else [bar.open, bar.high, bar.low, bar.close])
    prices = []
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        prices.extend([a, (a + b) / 2])
    prices.append(path[-1])
    step = 60.0 / len(prices)
    vol_each = max(1, bar.volume // len(prices))
    return [Quote(ts=bar.ts + i * step, last=p, bid=p - 0.25, ask=p + 0.25,
                  last_size=vol_each) for i, p in enumerate(prices)]


def split_warmup(bars: list[Bar], warmup_sessions: int) -> tuple[list[Bar], list[Bar]]:
    """Split so the engine warms on the first N trading sessions."""
    sessions: list[str] = []
    for b in bars:
        s = session_date(b.ts)
        if not sessions or sessions[-1] != s:
            sessions.append(s)
    if len(sessions) <= warmup_sessions:
        return bars, []
    first_live = sessions[warmup_sessions]
    for i, b in enumerate(bars):
        if session_date(b.ts) == first_live:
            return bars[:i], bars[i:]
    return bars, []


class Backtest:
    def __init__(self, settings: Settings | None = None,
                 triggers: set[str] | None = None,
                 bracket_override: tuple[float, float] | None = None):
        self.settings = settings or Settings()
        self.engine = SignalEngine(self.settings)
        if triggers:
            self.engine.trigger_tags = set(triggers)
        self.bracket_override = bracket_override  # (target_pts, stop_pts)
        self.journal = Journal(":memory:", self.settings, self.engine.breaker)
        self.signals: list[Signal] = []
        self.engine.on_signal = self._on_signal

    def _on_signal(self, s: Signal) -> None:
        if self.bracket_override:
            t_pts, s_pts = self.bracket_override
            sign = 1 if s.direction.value == "LONG" else -1
            s.target1 = s.entry + sign * t_pts
            s.target2 = s.entry + sign * t_pts
            s.stop = s.entry - sign * s_pts
            s.contracts = 1
            s.risk_dollars = s_pts * 2.0
        self.signals.append(s)
        self.journal.record(s)
        self.engine.active_signal = s

    def run(self, bars: list[Bar], warmup_sessions: int = 5) -> dict:
        warm, live = split_warmup(bars, warmup_sessions)
        self.engine.seed_history(warm)
        t0 = time.time()
        for bar in live:
            for q in bar_to_quotes(bar):
                self.journal.on_quote(q)
                self.engine.active_signal = self.journal.open_signal
                self.engine.on_quote(q)
        elapsed = time.time() - t0
        stats = self.detailed_stats()
        stats["bars_replayed"] = len(live)
        stats["sessions"] = len({session_date(b.ts) for b in live})
        stats["elapsed_sec"] = round(elapsed, 1)
        return stats

    # -- reporting ---------------------------------------------------------------

    def detailed_stats(self) -> dict:
        """Expectancy / profit-factor / drawdown stats, overall and per setup."""
        rows = [r for r in self.journal.recent(100000)
                if r["status"] in ("TARGET1", "TARGET2", "STOPPED", "FLAT_EXIT")]
        rows.sort(key=lambda r: r["ts"])

        def bucket(rs: list[dict]) -> dict:
            pnls = [r["pnl_dollars"] or 0.0 for r in rs]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            gross_win = sum(wins)
            gross_loss = -sum(losses)
            equity, peak, max_dd = 0.0, 0.0, 0.0
            for p in pnls:
                equity += p
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)
            return {
                "n": len(rs),
                "win_rate": round(100 * len(wins) / len(rs), 1) if rs else 0.0,
                "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
                "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
                "expectancy": round(sum(pnls) / len(rs), 2) if rs else 0.0,
                "profit_factor": (round(gross_win / gross_loss, 2)
                                  if gross_loss > 0 else None),
                "pnl": round(sum(pnls), 2),
                "max_dd": round(max_dd, 2),
            }

        by_setup = {}
        for r in rows:
            by_setup.setdefault(r["setup_type"], []).append(r)
        stats = bucket(rows)
        stats["signals"] = len(self.signals)
        stats["by_setup"] = {k: bucket(v) for k, v in
                             sorted(by_setup.items(),
                                    key=lambda kv: -sum(r["pnl_dollars"] or 0
                                                        for r in kv[1]))}
        return stats


def print_report(stats: dict, label: str = "") -> None:
    print(f"\n=== Backtest report {label} ===")
    print(f"bars replayed : {stats['bars_replayed']} over "
          f"{stats['sessions']} sessions ({stats['elapsed_sec']}s)")
    print(f"signals fired : {stats['signals']}   resolved: {stats['n']}")
    print(f"win rate      : {stats['win_rate']}%  "
          f"(avg win ${stats['avg_win']} / avg loss ${stats['avg_loss']})")
    print(f"expectancy    : ${stats['expectancy']}/trade   "
          f"profit factor: {stats['profit_factor']}")
    print(f"net P&L       : ${stats['pnl']}   max drawdown: ${stats['max_dd']}")
    if stats["by_setup"]:
        print(f"{'setup':<14}{'n':>4}{'win%':>7}{'exp$':>8}{'PF':>6}"
              f"{'P&L$':>9}{'maxDD$':>9}")
        for name, s in stats["by_setup"].items():
            pf = s["profit_factor"] if s["profit_factor"] is not None else "inf"
            print(f"{name:<14}{s['n']:>4}{s['win_rate']:>7}{s['expectancy']:>8}"
                  f"{pf:>6}{s['pnl']:>9}{s['max_dd']:>9}")
    print()


def load_bars(path: str) -> list[Bar]:
    raw = json.loads(Path(path).read_text())
    return [Bar(b["time"], b["open"], b["high"], b["low"], b["close"],
                int(b.get("volume", 0))) for b in raw]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--file", type=str, default=None,
                        help="JSON file of 1m bars [{time,open,high,low,close,volume}]")
    parser.add_argument("--warmup-sessions", type=int, default=5)
    parser.add_argument("--triggers", type=str, default=None,
                        help="comma-separated: only these tags may trigger a call")
    parser.add_argument("--measure", action="store_true",
                        help="edge measurement mode: breaker off so one bad "
                             "morning doesn't truncate the sample")
    parser.add_argument("--loose-choch", action="store_true",
                        help="legacy CHoCH (fires on ranging breaks)")
    parser.add_argument("--bracket", type=str, default=None,
                        help="override bracket as TARGET_PTS,STOP_PTS "
                             "(e.g. 2,40 for the high-win-rate demo)")
    parser.add_argument("--max-age", type=int, default=None,
                        help="override max_signal_age_min")
    parser.add_argument("--cooldown", type=int, default=None,
                        help="override signal_cooldown_sec")
    parser.add_argument("--fire-b", type=float, default=None,
                        help="override score_fire_b threshold")
    parser.add_argument("--t2", type=float, default=None,
                        help="override target2_r (runner target, in R)")
    parser.add_argument("--json-out", type=str, default=None)
    parser.add_argument("--dump-trades", type=str, default=None,
                        help="write per-trade rows to this JSON file")
    args = parser.parse_args()

    if args.file:
        bars = load_bars(args.file)
        print(f"loaded {len(bars)} bars from {args.file}")
    else:
        from app.feed.sim_feed import generate_history
        bars = generate_history(days=args.days, seed=args.seed)
        print(f"generated {len(bars)} synthetic 1m bars (seed {args.seed})")

    settings = Settings()
    if args.measure:
        settings.circuit_breaker_enabled = False
    if args.loose_choch:
        settings.strict_choch = False
    if args.max_age:
        settings.max_signal_age_min = args.max_age
    if args.cooldown is not None:
        settings.signal_cooldown_sec = args.cooldown
    if args.fire_b is not None:
        settings.score_fire_b = args.fire_b
    if args.t2 is not None:
        settings.target2_r = args.t2
    triggers = set(args.triggers.split(",")) if args.triggers else None
    bracket = None
    if args.bracket:
        t, s = args.bracket.split(",")
        bracket = (float(t), float(s))

    bt = Backtest(settings, triggers=triggers, bracket_override=bracket)
    stats = bt.run(bars, warmup_sessions=args.warmup_sessions)
    label = f"[triggers={args.triggers}]" if args.triggers else "[full engine]"
    print_report(stats, label)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(stats, indent=2))
    if args.dump_trades:
        rows = [r for r in bt.journal.recent(100000)
                if r["status"] in ("TARGET1", "TARGET2", "STOPPED", "FLAT_EXIT")]
        Path(args.dump_trades).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
