"""Indicator primitives.

All functions take plain lists of floats/Bars (newest last) and return either
a single latest value or a list aligned with the input. Kept dependency-light
so the exact same code runs live and in backtests.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from app.models import Bar


# -- moving averages ----------------------------------------------------------

def ema_series(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return ema_series(values, period)[-1]


# -- oscillators ---------------------------------------------------------------

def rsi_series(closes: Sequence[float], period: int = 14) -> list[Optional[float]]:
    n = len(closes)
    out: list[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def rsi(closes: Sequence[float], period: int = 14) -> Optional[float]:
    series = rsi_series(closes, period)
    return series[-1] if series else None


def rate_of_change(closes: Sequence[float], period: int = 10) -> Optional[float]:
    if len(closes) < period + 1 or closes[-period - 1] == 0:
        return None
    return (closes[-1] - closes[-period - 1]) / closes[-period - 1] * 100.0


# -- volatility -----------------------------------------------------------------

def atr(bars: Sequence[Bar], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(len(bars) - period, len(bars)):
        b, prev = bars[i], bars[i - 1]
        trs.append(max(b.high - b.low,
                       abs(b.high - prev.close),
                       abs(b.low - prev.close)))
    return sum(trs) / len(trs)


# -- VWAP -----------------------------------------------------------------------

@dataclass
class VwapState:
    """Incrementally maintained session VWAP with volume-weighted std bands."""

    cum_vol: float = 0.0
    cum_pv: float = 0.0
    cum_pv2: float = 0.0

    def reset(self) -> None:
        self.cum_vol = self.cum_pv = self.cum_pv2 = 0.0

    def add_bar(self, bar: Bar) -> None:
        typical = (bar.high + bar.low + bar.close) / 3.0
        vol = max(bar.volume, 1)
        self.cum_vol += vol
        self.cum_pv += typical * vol
        self.cum_pv2 += typical * typical * vol

    @property
    def vwap(self) -> Optional[float]:
        if self.cum_vol <= 0:
            return None
        return self.cum_pv / self.cum_vol

    @property
    def sigma(self) -> Optional[float]:
        if self.cum_vol <= 0:
            return None
        mean = self.cum_pv / self.cum_vol
        var = max(self.cum_pv2 / self.cum_vol - mean * mean, 0.0)
        return math.sqrt(var)

    def bands(self, k: float) -> Optional[tuple[float, float]]:
        v, s = self.vwap, self.sigma
        if v is None or s is None:
            return None
        return (v - k * s, v + k * s)


# -- volume ----------------------------------------------------------------------

def relative_volume(bars: Sequence[Bar], lookback: int = 20) -> Optional[float]:
    """Volume of the latest closed bar vs the average of the prior `lookback`."""
    if len(bars) < lookback + 1:
        return None
    recent = bars[-1].volume
    prior = [b.volume for b in bars[-lookback - 1:-1]]
    avg = sum(prior) / len(prior)
    if avg <= 0:
        return None
    return recent / avg


def is_volume_climax(bars: Sequence[Bar], lookback: int = 30, mult: float = 3.0) -> bool:
    rv = relative_volume(bars, lookback)
    return rv is not None and rv >= mult


# -- swings & divergence -----------------------------------------------------------

def swing_points(bars: Sequence[Bar], strength: int = 3) -> tuple[list[int], list[int]]:
    """Indexes of swing highs and lows (fractal style, `strength` bars each side)."""
    highs, lows = [], []
    for i in range(strength, len(bars) - strength):
        window = bars[i - strength: i + strength + 1]
        if bars[i].high == max(b.high for b in window):
            highs.append(i)
        if bars[i].low == min(b.low for b in window):
            lows.append(i)
    return highs, lows


def rsi_divergence(bars: Sequence[Bar], period: int = 14,
                   strength: int = 3) -> Optional[str]:
    """Returns 'bullish', 'bearish' or None using the last two swing points."""
    if len(bars) < period + 2 * strength + 5:
        return None
    closes = [b.close for b in bars]
    rsis = rsi_series(closes, period)
    highs, lows = swing_points(bars, strength)

    if len(lows) >= 2:
        i1, i2 = lows[-2], lows[-1]
        if (rsis[i1] is not None and rsis[i2] is not None
                and bars[i2].low < bars[i1].low and rsis[i2] > rsis[i1] + 1.0):
            return "bullish"
    if len(highs) >= 2:
        i1, i2 = highs[-2], highs[-1]
        if (rsis[i1] is not None and rsis[i2] is not None
                and bars[i2].high > bars[i1].high and rsis[i2] < rsis[i1] - 1.0):
            return "bearish"
    return None


# -- candlestick patterns ------------------------------------------------------------

def is_bullish_engulfing(prev: Bar, cur: Bar) -> bool:
    return (prev.close < prev.open
            and cur.close > cur.open
            and cur.close >= prev.open
            and cur.open <= prev.close
            and _body(cur) > _body(prev) * 1.1)


def is_bearish_engulfing(prev: Bar, cur: Bar) -> bool:
    return (prev.close > prev.open
            and cur.close < cur.open
            and cur.close <= prev.open
            and cur.open >= prev.close
            and _body(cur) > _body(prev) * 1.1)


def is_bullish_pin(bar: Bar) -> bool:
    """Long lower wick rejection candle (hammer)."""
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    lower_wick = min(bar.open, bar.close) - bar.low
    return lower_wick >= rng * 0.6 and _body(bar) <= rng * 0.3


def is_bearish_pin(bar: Bar) -> bool:
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    upper_wick = bar.high - max(bar.open, bar.close)
    return upper_wick >= rng * 0.6 and _body(bar) <= rng * 0.3


def _body(bar: Bar) -> float:
    return abs(bar.close - bar.open)


def double_top_bottom(bars: Sequence[Bar], strength: int = 3,
                      tolerance_pts: float = 6.0) -> Optional[str]:
    """Detects a recent double top ('top') or double bottom ('bottom')."""
    highs, lows = swing_points(bars, strength)
    n = len(bars)
    if len(highs) >= 2:
        i1, i2 = highs[-2], highs[-1]
        if (n - i2 <= strength + 3 and i2 - i1 >= 4
                and abs(bars[i1].high - bars[i2].high) <= tolerance_pts):
            return "top"
    if len(lows) >= 2:
        i1, i2 = lows[-2], lows[-1]
        if (n - i2 <= strength + 3 and i2 - i1 >= 4
                and abs(bars[i1].low - bars[i2].low) <= tolerance_pts):
            return "bottom"
    return None
