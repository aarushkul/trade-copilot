"""Multi-timeframe bar aggregation from tick/quote updates."""
from __future__ import annotations

from collections import deque
from typing import Callable, Iterable, Optional

from app.models import Bar, Quote

# Timeframes the engine consumes, in seconds.
TIMEFRAMES = {
    "15s": 15,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
}


class BarSeries:
    """Rolling window of closed bars for one timeframe plus the forming bar."""

    def __init__(self, tf_seconds: int, maxlen: int = 3000):
        self.tf = tf_seconds
        self.bars: deque[Bar] = deque(maxlen=maxlen)
        self.forming: Optional[Bar] = None

    def bucket(self, ts: float) -> float:
        return ts - (ts % self.tf)

    def seed(self, bars: Iterable[Bar]) -> None:
        """Seed with historical closed bars (oldest first)."""
        for b in bars:
            self.bars.append(b)

    def on_quote(self, q: Quote) -> Optional[Bar]:
        """Update the forming bar; returns the just-closed bar on rollover."""
        bucket = self.bucket(q.ts)
        closed = None
        if self.forming is None:
            if self.bars and self.bars[-1].ts >= bucket:
                # Seeded history (e.g. Schwab) includes the current partial
                # bar. Resume it as the forming bar instead of creating a
                # duplicate timestamp, which corrupts indicators and charts.
                self.forming = self.bars.pop()
                self.forming.update(q.last, q.last_size)
            else:
                self.forming = Bar(bucket, q.last, q.last, q.last, q.last, q.last_size)
        elif bucket > self.forming.ts:
            closed = self.forming
            self.bars.append(closed)
            self.forming = Bar(bucket, q.last, q.last, q.last, q.last, q.last_size)
        else:
            self.forming.update(q.last, q.last_size)
        return closed

    # -- convenience accessors ------------------------------------------------

    def closes(self, n: int) -> list[float]:
        return [b.close for b in list(self.bars)[-n:]]

    def last_bars(self, n: int) -> list[Bar]:
        return list(self.bars)[-n:]

    def __len__(self) -> int:
        return len(self.bars)


class BarBuilder:
    """Feeds one quote stream into all timeframes at once."""

    def __init__(self):
        self.series: dict[str, BarSeries] = {
            name: BarSeries(sec) for name, sec in TIMEFRAMES.items()
        }
        self.on_bar_close: Optional[Callable[[str, Bar], None]] = None

    def seed_from_minute_bars(self, minute_bars: list[Bar]) -> None:
        """Warm every timeframe from historical 1m bars (oldest first)."""
        self.series["1m"].seed(minute_bars)
        for name, sec in TIMEFRAMES.items():
            if name in ("1m", "15s"):
                continue
            agg: list[Bar] = []
            current: Optional[Bar] = None
            for mb in minute_bars:
                bucket = mb.ts - (mb.ts % sec)
                if current is None or bucket > current.ts:
                    if current is not None:
                        agg.append(current)
                    current = Bar(bucket, mb.open, mb.high, mb.low, mb.close, mb.volume)
                else:
                    current.high = max(current.high, mb.high)
                    current.low = min(current.low, mb.low)
                    current.close = mb.close
                    current.volume += mb.volume
            if current is not None:
                agg.append(current)
            self.series[name].seed(agg)

    def on_quote(self, q: Quote) -> list[tuple[str, Bar]]:
        """Returns list of (timeframe, closed_bar) that rolled on this quote."""
        closed: list[tuple[str, Bar]] = []
        for name, series in self.series.items():
            bar = series.on_quote(q)
            if bar is not None:
                closed.append((name, bar))
                if self.on_bar_close:
                    self.on_bar_close(name, bar)
        return closed
