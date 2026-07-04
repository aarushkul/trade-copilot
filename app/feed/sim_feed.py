"""Simulated MNQ feed: regime-switching random walk with a session volume curve.

Used to develop/demo the whole stack before Schwab credentials exist, and to
generate synthetic history for backtest sanity checks.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Callable, Optional

from app.engine.session import is_rth, phase_at, Phase, to_et
from app.models import Bar, Quote

TICK = 0.25


def _round_tick(p: float) -> float:
    return round(round(p / TICK) * TICK, 2)


class Regime:
    """Drift/vol regime that persists for a while, then switches."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.drift = 0.0
        self.vol_mult = 1.0
        self.until = 0.0

    def maybe_switch(self, ts: float) -> None:
        if ts < self.until:
            return
        mode = self.rng.choices(["trend_up", "trend_down", "chop", "normal"],
                                weights=[0.22, 0.22, 0.28, 0.28])[0]
        if mode == "trend_up":
            self.drift, self.vol_mult = 0.045, 1.15
        elif mode == "trend_down":
            self.drift, self.vol_mult = -0.045, 1.15
        elif mode == "chop":
            self.drift, self.vol_mult = 0.0, 0.45
        else:
            self.drift, self.vol_mult = 0.0, 1.0
        self.until = ts + self.rng.uniform(20 * 60, 90 * 60)


def _session_vol(ts: float) -> float:
    """Per-second point sigma by session phase (MNQ-ish)."""
    phase = phase_at(ts)
    return {
        Phase.OPEN_QUIET: 2.6, Phase.OPEN_DRIVE: 2.4, Phase.MORNING: 1.7,
        Phase.LUNCH: 1.0, Phase.AFTERNOON: 1.6, Phase.CLOSE: 2.0,
        Phase.PREMARKET: 0.9, Phase.OVERNIGHT: 0.6, Phase.CLOSED: 0.0,
    }[phase]


class SimFeed:
    def __init__(self, start_price: float = 24800.0, seed: Optional[int] = None,
                 hz: float = 5.0):
        self.rng = random.Random(seed)
        self.price = start_price
        self.hz = hz
        self.regime = Regime(self.rng)
        self.day_volume = 0
        self._running = False

    async def run(self, on_quote: Callable[[Quote], None]) -> None:
        self._running = True
        dt = 1.0 / self.hz
        while self._running:
            ts = time.time()
            self.regime.maybe_switch(ts)
            # Demo feed never sleeps: keep a floor on volatility so the
            # dashboard is alive even when the real market is closed.
            sigma = max(_session_vol(ts), 1.6) * self.regime.vol_mult
            if sigma > 0:
                step = self.rng.gauss(self.regime.drift * dt, sigma * math.sqrt(dt))
                self.price = max(100.0, self.price + step)
                size = max(1, int(self.rng.expovariate(1 / 3.0)))
                self.day_volume += size
                last = _round_tick(self.price)
                on_quote(Quote(ts=ts, last=last, bid=last - TICK, ask=last + TICK,
                               last_size=size, day_volume=self.day_volume))
            await asyncio.sleep(dt)

    def stop(self) -> None:
        self._running = False


def generate_history(days: int = 10, start_price: float = 24800.0,
                     seed: Optional[int] = None,
                     end_ts: Optional[float] = None) -> list[Bar]:
    """Synthetic 1m bars for the past `days`, matching CME hours."""
    rng = random.Random(seed)
    end = end_ts if end_ts is not None else time.time()
    start = end - days * 86400
    regime = Regime(rng)
    price = start_price
    bars: list[Bar] = []

    ts = start - (start % 60)
    while ts < end - 60:
        dt_et = to_et(ts)
        weekday, t = dt_et.weekday(), dt_et.time()
        closed = (weekday == 5 or (weekday == 4 and t.hour >= 17)
                  or (weekday == 6 and t.hour < 18) or t.hour == 17)
        if closed:
            ts += 60
            continue
        regime.maybe_switch(ts)
        sigma_min = _session_vol(ts) * regime.vol_mult * math.sqrt(60)
        if sigma_min <= 0:
            ts += 60
            continue
        o = price
        drift = regime.drift * 60
        c = max(100.0, o + rng.gauss(drift, sigma_min))
        hi = max(o, c) + abs(rng.gauss(0, sigma_min * 0.35))
        lo = min(o, c) - abs(rng.gauss(0, sigma_min * 0.35))
        base_vol = 900 if is_rth(ts) else 150
        vol = max(10, int(rng.gauss(base_vol, base_vol * 0.4)))
        bars.append(Bar(ts, _round_tick(o), _round_tick(hi), _round_tick(lo),
                        _round_tick(c), vol))
        price = c
        ts += 60
    return bars
