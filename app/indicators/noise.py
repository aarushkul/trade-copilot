"""Time-of-day noise bands for intraday momentum / trend-day detection.

Concept (Zarattini, Barbon & Aziz, "Beat the Market", SSRN 4824172): for each
minute of the RTH session, measure the average absolute move from the RTH open
over the trailing N sessions. Price beyond `open ± k * that average` is a
statistically abnormal displacement for that time of day — evidence of real
directional imbalance (trend day) rather than noise. Inside the band, moves
are within normal wander and breakouts carry no edge.

Used two ways:
- trigger: noise_momentum setup votes with a fresh band cross
- regime filter: VWAP band fades are suppressed while price is beyond the band
"""
from __future__ import annotations

from collections import deque
from typing import Optional

from app.engine.session import RTH_OPEN, is_rth, to_et
from app.models import Bar

RTH_MINUTES = 390  # 9:30 - 16:00


class NoiseBands:
    """Feed it 1m bars (live or seeded history); ask for today's bands."""

    def __init__(self, lookback_sessions: int = 14, min_sessions: int = 8,
                 k: float = 1.0):
        self.lookback = lookback_sessions
        self.min_sessions = min_sessions
        self.k = k
        # Completed sessions: each is a list of abs-move-fraction by minute idx.
        self._profiles: deque[list[Optional[float]]] = deque(maxlen=lookback_sessions)
        self._cur_date: Optional[str] = None
        self._cur_open: Optional[float] = None
        self._cur_profile: list[Optional[float]] = []
        self.today_open: Optional[float] = None

    @staticmethod
    def _minute_index(ts: float) -> int:
        dt = to_et(ts)
        return (dt.hour - RTH_OPEN.hour) * 60 + (dt.minute - RTH_OPEN.minute)

    def on_minute_bar(self, bar: Bar) -> None:
        if not is_rth(bar.ts):
            return
        date = to_et(bar.ts).strftime("%Y-%m-%d")
        if date != self._cur_date:
            if self._cur_profile and self._cur_open:
                self._profiles.append(self._cur_profile)
            self._cur_date = date
            self._cur_open = bar.open
            self._cur_profile = [None] * RTH_MINUTES
            self.today_open = bar.open
        idx = self._minute_index(bar.ts)
        if 0 <= idx < RTH_MINUTES and self._cur_open:
            self._cur_profile[idx] = abs(bar.close - self._cur_open) / self._cur_open

    @property
    def ready(self) -> bool:
        return len(self._profiles) >= self.min_sessions and self.today_open is not None

    def avg_move(self, minute_idx: int) -> Optional[float]:
        """Average abs move fraction at this minute over stored sessions."""
        if not self._profiles:
            return None
        # Early minutes have tiny average moves; use a floor of minute 5's
        # sample so the first minutes don't produce a zero-width band.
        idx = max(5, min(minute_idx, RTH_MINUTES - 1))
        vals = [p[idx] for p in self._profiles if p[idx] is not None]
        if not vals:
            return None
        return sum(vals) / len(vals)

    def bands_at(self, ts: float) -> Optional[tuple[float, float]]:
        """(lower, upper) noise band for the current session at time ts."""
        if not self.ready or not is_rth(ts):
            return None
        avg = self.avg_move(self._minute_index(ts))
        if avg is None or self.today_open is None:
            return None
        width = self.k * avg * self.today_open
        return (self.today_open - width, self.today_open + width)
