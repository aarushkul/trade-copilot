"""Backtest/replay harness: run the exact live engine over historical 1m bars.

Each 1m bar is expanded into 8 synthetic quotes tracing an O-H-L-C path so the
engine's 15s evaluation cadence, journal tracking, stops and targets all work
the same way they do live. Not an institutional backtester - a tuning tool.

Usage:
    .venv/bin/python -m app.backtest.replay --days 10 --seed 7
    .venv/bin/python -m app.backtest.replay --file data/history/mnq_1m.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.config import Settings
from app.engine.engine import SignalEngine
from app.engine.risk import CircuitBreaker
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


class Backtest:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.engine = SignalEngine(self.settings)
        self.journal = Journal(":memory:", self.settings, self.engine.breaker)
        self.signals: list[Signal] = []
        self.engine.on_signal = self._on_signal

    def _on_signal(self, s: Signal) -> None:
        self.signals.append(s)
        self.journal.record(s)
        self.engine.active_signal = s

    def run(self, bars: list[Bar], warmup_bars: int = 600) -> dict:
        warm, live = bars[:warmup_bars], bars[warmup_bars:]
        self.engine.seed_history(warm)
        t0 = time.time()
        for bar in live:
            for q in bar_to_quotes(bar):
                self.journal.on_quote(q)
                self.engine.active_signal = self.journal.open_signal
                self.engine.on_quote(q)
        elapsed = time.time() - t0
        stats = self.journal.stats()
        stats["bars_replayed"] = len(live)
        stats["elapsed_sec"] = round(elapsed, 1)
        return stats


def print_report(stats: dict) -> None:
    print("\n=== Backtest report ===")
    print(f"bars replayed : {stats['bars_replayed']}  "
          f"({stats['elapsed_sec']}s)")
    print(f"signals fired : {stats['signals']}")
    print(f"resolved      : {stats['resolved']}  "
          f"(wins {stats['wins']} / losses {stats['losses']})")
    print(f"win rate      : {stats['win_rate']}%")
    print(f"total P&L     : ${stats['pnl_dollars']}")
    print(f"avg R         : {stats['avg_r']}")
    if stats["by_setup"]:
        print("by setup:")
        for name, s in sorted(stats["by_setup"].items(),
                              key=lambda kv: -kv[1]["pnl"]):
            print(f"  {name:<12} n={s['count']:<3} wins={s['wins']:<3} "
                  f"pnl=${s['pnl']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--file", type=str, default=None,
                        help="JSON file of 1m bars [{time,open,high,low,close,volume}]")
    args = parser.parse_args()

    if args.file:
        raw = json.loads(Path(args.file).read_text())
        bars = [Bar(b["time"], b["open"], b["high"], b["low"], b["close"],
                    int(b.get("volume", 0))) for b in raw]
        print(f"loaded {len(bars)} bars from {args.file}")
    else:
        from app.feed.sim_feed import generate_history
        bars = generate_history(days=args.days, seed=args.seed)
        print(f"generated {len(bars)} synthetic 1m bars (seed {args.seed})")

    stats = Backtest().run(bars)
    print_report(stats)


if __name__ == "__main__":
    main()
