"""Session awareness for CME equity index futures (ET clock).

Phases, prior-day / overnight / opening-range level tracking, and the
chop filter all live here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from app.indicators.core import atr
from app.models import Bar

ET = ZoneInfo("America/New_York")

RTH_OPEN = dtime(9, 30)
RTH_CLOSE = dtime(16, 0)
GLOBEX_OPEN = dtime(18, 0)
# End of the LUNCH phase (A-grade-only under lunch_a_grade_only). Tested at
# 14:00 on 25 replay sessions (2026-07-09) to block the weak 13:00 hour: no
# improvement once the circuit breaker is on, so it stays at the classic 13:30.
LUNCH_END = dtime(13, 30)


class Phase(str, Enum):
    OVERNIGHT = "OVERNIGHT"
    PREMARKET = "PREMARKET"     # 8:00 - 9:30
    OPEN_QUIET = "OPEN_QUIET"   # first N minutes after the bell
    OPEN_DRIVE = "OPEN_DRIVE"   # 9:30+N - 10:30
    MORNING = "MORNING"         # 10:30 - 12:00
    LUNCH = "LUNCH"             # 12:00 - LUNCH_END
    AFTERNOON = "AFTERNOON"     # LUNCH_END - 15:45
    CLOSE = "CLOSE"             # final minutes, no new entries
    CLOSED = "CLOSED"           # 16:00 - 18:00 daily maintenance


def to_et(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=ET)


def phase_at(ts: float, no_open_minutes: int = 5, last_entry_minutes: int = 15) -> Phase:
    dt = to_et(ts)
    t = dt.time()
    weekday = dt.weekday()

    # CME closes Fri 17:00, reopens Sun 18:00; maintenance 17:00-18:00 daily.
    if weekday == 5 or (weekday == 4 and t >= RTH_CLOSE) or \
       (weekday == 6 and t < GLOBEX_OPEN):
        return Phase.CLOSED
    # 16:00-18:00: post-close + maintenance. The journal force-flattens any
    # open signal in this window, so no phase logic may ever allow entries.
    if RTH_CLOSE <= t < GLOBEX_OPEN:
        return Phase.CLOSED

    if RTH_OPEN <= t < RTH_CLOSE:
        minutes_in = (dt.hour - 9) * 60 + dt.minute - 30
        minutes_left = (16 - dt.hour) * 60 - dt.minute
        if minutes_in < no_open_minutes:
            return Phase.OPEN_QUIET
        if minutes_left <= last_entry_minutes:
            return Phase.CLOSE
        if t < dtime(10, 30):
            return Phase.OPEN_DRIVE
        if t < dtime(12, 0):
            return Phase.MORNING
        if t < LUNCH_END:
            return Phase.LUNCH
        return Phase.AFTERNOON
    if dtime(8, 0) <= t < RTH_OPEN:
        return Phase.PREMARKET
    return Phase.OVERNIGHT


def is_rth(ts: float) -> bool:
    t = to_et(ts).time()
    return RTH_OPEN <= t < RTH_CLOSE and to_et(ts).weekday() < 5


def session_date(ts: float) -> str:
    """Trading-day key: overnight bars belong to the *next* RTH date.

    The 18:00 ET Globex open starts the next trading day, so Monday 19:00
    and Tuesday 02:00 map to the same key ("Tuesday"). Anything else (e.g.
    a midnight-based key) would reset session VWAP mid-Globex-session.
    """
    dt = to_et(ts)
    if dt.time() >= GLOBEX_OPEN:
        return (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")


@dataclass
class Levels:
    prior_day_high: Optional[float] = None
    prior_day_low: Optional[float] = None
    prior_day_close: Optional[float] = None
    overnight_high: Optional[float] = None
    overnight_low: Optional[float] = None
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    opening_range_high: Optional[float] = None
    opening_range_low: Optional[float] = None
    opening_range_done: bool = False

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    def named_levels(self) -> list[tuple[str, float]]:
        pairs = [
            ("PDH", self.prior_day_high), ("PDL", self.prior_day_low),
            ("PDC", self.prior_day_close),
            ("ONH", self.overnight_high), ("ONL", self.overnight_low),
            ("ORH", self.opening_range_high if self.opening_range_done else None),
            ("ORL", self.opening_range_low if self.opening_range_done else None),
        ]
        return [(n, v) for n, v in pairs if v is not None]


class LevelTracker:
    """Feed it 1m bars (live or historical) and it maintains key levels."""

    OR_MINUTES = 15  # opening range length

    def __init__(self):
        self.levels = Levels()
        self._rth_date: Optional[str] = None
        self._cur_rth_high: Optional[float] = None
        self._cur_rth_low: Optional[float] = None
        self._cur_rth_close: Optional[float] = None

    def on_minute_bar(self, bar: Bar) -> None:
        dt = to_et(bar.ts)
        t = dt.time()
        date = dt.strftime("%Y-%m-%d")

        if RTH_OPEN <= t < RTH_CLOSE:
            if self._rth_date != date:
                # New RTH session: promote yesterday's running values.
                if self._cur_rth_high is not None:
                    self.levels.prior_day_high = self._cur_rth_high
                    self.levels.prior_day_low = self._cur_rth_low
                    self.levels.prior_day_close = self._cur_rth_close
                self._rth_date = date
                self._cur_rth_high = bar.high
                self._cur_rth_low = bar.low
                self.levels.session_high = bar.high
                self.levels.session_low = bar.low
                self.levels.opening_range_high = bar.high
                self.levels.opening_range_low = bar.low
                self.levels.opening_range_done = False
            else:
                self._cur_rth_high = max(self._cur_rth_high, bar.high)
                self._cur_rth_low = min(self._cur_rth_low, bar.low)
                self.levels.session_high = max(self.levels.session_high, bar.high)
                self.levels.session_low = min(self.levels.session_low, bar.low)
            self._cur_rth_close = bar.close

            minutes_in = (dt.hour - 9) * 60 + dt.minute - 30
            if minutes_in < self.OR_MINUTES:
                self.levels.opening_range_high = max(
                    self.levels.opening_range_high or bar.high, bar.high)
                self.levels.opening_range_low = min(
                    self.levels.opening_range_low or bar.low, bar.low)
            else:
                self.levels.opening_range_done = True
        else:
            # Overnight (Globex) session: reset at 18:00 open.
            if t >= GLOBEX_OPEN and (self.levels.overnight_high is None
                                     or self._is_globex_open_bar(dt)):
                self.levels.overnight_high = bar.high
                self.levels.overnight_low = bar.low
            else:
                if self.levels.overnight_high is not None:
                    self.levels.overnight_high = max(self.levels.overnight_high, bar.high)
                    self.levels.overnight_low = min(self.levels.overnight_low, bar.low)
                else:
                    self.levels.overnight_high = bar.high
                    self.levels.overnight_low = bar.low

    @staticmethod
    def _is_globex_open_bar(dt: datetime) -> bool:
        return dt.time() >= GLOBEX_OPEN and dt.time() < dtime(18, 1)


@dataclass
class ChopReport:
    is_chop: bool
    detail: str = ""


def chop_filter(bars_1m: list[Bar], bars_5m: list[Bar]) -> ChopReport:
    """Rangebound tape detector.

    Chop when the last 30 minutes of price action is compressed relative to
    recent 5m volatility: nobody is in control, breakouts fail, spreads eat you.
    """
    if len(bars_1m) < 30 or len(bars_5m) < 20:
        return ChopReport(False, "warming up")
    window = bars_1m[-30:]
    rng = max(b.high for b in window) - min(b.low for b in window)
    a5 = atr(bars_5m, 14)
    if a5 is None or a5 <= 0:
        return ChopReport(False, "no ATR")
    ratio = rng / a5
    if ratio < 1.6:
        return ChopReport(True, f"30m range {rng:.1f} pts is only "
                                f"{ratio:.1f}x the 5m ATR ({a5:.1f})")
    return ChopReport(False, f"30m range {rng:.1f} pts, {ratio:.1f}x 5m ATR")
