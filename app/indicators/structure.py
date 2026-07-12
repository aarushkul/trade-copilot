"""ICT-style market structure: swings, BOS, CHoCH, liquidity sweeps.

Definitions (institutional / ICT framing, coded deterministically):

- **Swing high/low**: fractal pivot — highest/lowest in `strength` bars each side.
- **Bias**: bullish = HH+HL on last two swings; bearish = LH+LL; else ranging.
- **BOS (Break of Structure)**: continuation — close beyond the prior swing extreme
  *in the direction of the established bias* (bullish BOS breaks prior SH).
- **CHoCH (Change of Character)**: first structural shift — close beyond the
  protected swing *against* the prior bias (bearish→bullish breaks last SH while
  bias was bearish/ranging-from-bearish; mirror for bearish CHoCH).
- **Liquidity sweep**: wick takes out a recent swing extreme, close reclaims inside
  (stop-run / turtle soup) — classic ICT inducement before reversal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional, Sequence

from app.indicators.core import atr, swing_points
from app.models import Bar, Direction

Bias = Literal["bullish", "bearish", "ranging", "unknown"]


class StructureKind(str, Enum):
    BOS = "BOS"
    CHOCH = "CHoCH"
    SWEEP = "SWEEP"


@dataclass
class SwingLevel:
    index: int
    price: float


@dataclass
class StructureEvent:
    kind: StructureKind
    direction: Direction          # LONG = bullish event, SHORT = bearish
    level: float
    bar_index: int
    bars_ago: int                 # 0 = just happened on latest bar
    timeframe: str = ""

    def label(self) -> str:
        d = "bullish" if self.direction == Direction.LONG else "bearish"
        return f"{self.kind.value} ({d}) @ {self.level:.2f}"


@dataclass
class TimeframeStructure:
    timeframe: str
    bias: Bias = "unknown"
    last_swing_high: Optional[SwingLevel] = None
    last_swing_low: Optional[SwingLevel] = None
    protected_swing: Optional[float] = None   # HL in uptrend, LH in downtrend
    last_event: Optional[StructureEvent] = None
    events_recent: list[StructureEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "bias": self.bias,
            "last_swing_high": self.last_swing_high.price if self.last_swing_high else None,
            "last_swing_low": self.last_swing_low.price if self.last_swing_low else None,
            "protected_swing": self.protected_swing,
            "last_event": None if self.last_event is None else {
                "kind": self.last_event.kind.value,
                "direction": self.last_event.direction.value,
                "level": round(self.last_event.level, 2),
                "bars_ago": self.last_event.bars_ago,
            },
        }


# Per-timeframe fractal strength (bars each side of pivot).
TF_STRENGTH = {"1m": 3, "5m": 2, "15m": 2, "1h": 2}


def _swing_levels(bars: Sequence[Bar], strength: int) -> tuple[list[SwingLevel], list[SwingLevel]]:
    hi_idx, lo_idx = swing_points(bars, strength)
    highs = [SwingLevel(i, bars[i].high) for i in hi_idx]
    lows = [SwingLevel(i, bars[i].low) for i in lo_idx]
    return highs, lows


def classify_bias(highs: list[SwingLevel], lows: list[SwingLevel]) -> Bias:
    if len(highs) < 2 or len(lows) < 2:
        return "unknown"
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl:
        return "bullish"
    if lh and ll:
        return "bearish"
    return "ranging"


def _protected_swing(bias: Bias, highs: list[SwingLevel],
                     lows: list[SwingLevel]) -> Optional[float]:
    """The swing that must hold in a trend (HL for bulls, LH for bears)."""
    if bias == "bullish" and len(lows) >= 1:
        return lows[-1].price
    if bias == "bearish" and len(highs) >= 1:
        return highs[-1].price
    return None


def _detect_events(bars: Sequence[Bar], highs: list[SwingLevel], lows: list[SwingLevel],
                   bias: Bias, tf: str, scan_bars: int = 8,
                   strict_choch: bool = True) -> list[StructureEvent]:
    """Scan recent closed bars for BOS / CHoCH.

    strict_choch=True: a CHoCH needs an established *opposite* trend to shift
    from (textbook ICT). False also fires on ranging-bias breaks, which turns
    every minor range poke into a "reversal" — measured on real MNQ tape that
    fires constantly in chop and was the worst live performer.
    """
    if len(bars) < 10 or not highs or not lows:
        return []
    events: list[StructureEvent] = []
    seen: set[tuple[StructureKind, Direction, float]] = set()
    n = len(bars)
    start = max(1, n - scan_bars)

    def _emit(kind: StructureKind, direction: Direction, level: float, bi: int) -> None:
        # A level is broken once. Later bars that merely stay beyond it are
        # continuation, not fresh structure - without this, one break casts
        # a duplicate vote on every subsequent bar and fabricates confluence.
        key = (kind, direction, level)
        if key in seen:
            return
        seen.add(key)
        events.append(StructureEvent(kind, direction, level, bi, n - 1 - bi, tf))

    for bi in range(start, n):
        bar = bars[bi]
        # Swings known *before* this bar (exclude future swings).
        sh = [h for h in highs if h.index < bi]
        sl = [l for l in lows if l.index < bi]
        if not sh or not sl:
            continue
        last_sh, prev_sh = sh[-1], sh[-2] if len(sh) >= 2 else sh[-1]
        last_sl, prev_sl = sl[-1], sl[-2] if len(sl) >= 2 else sl[-1]
        local_bias = classify_bias(sh[-2:] if len(sh) >= 2 else sh,
                                   sl[-2:] if len(sl) >= 2 else sl)

        choch_from_bull = ("bullish",) if strict_choch else ("bullish", "ranging")
        choch_from_bear = ("bearish",) if strict_choch else ("bearish", "ranging")

        close = bar.close
        # --- Bullish breaks ---
        if close > last_sh.price:
            if local_bias in choch_from_bear:
                _emit(StructureKind.CHOCH, Direction.LONG, last_sh.price, bi)
            elif local_bias == "bullish" and close > prev_sh.price:
                _emit(StructureKind.BOS, Direction.LONG, last_sh.price, bi)
        # --- Bearish breaks ---
        if close < last_sl.price:
            if local_bias in choch_from_bull:
                _emit(StructureKind.CHOCH, Direction.SHORT, last_sl.price, bi)
            elif local_bias == "bearish" and close < prev_sl.price:
                _emit(StructureKind.BOS, Direction.SHORT, last_sl.price, bi)

    return events


def _detect_sweeps(bars: Sequence[Bar], highs: list[SwingLevel], lows: list[SwingLevel],
                   tf: str, scan_bars: int = 5,
                   min_depth: float = 0.5) -> list[StructureEvent]:
    """Liquidity sweep: wick through swing by min_depth, close back the other side.

    min_depth is ATR-scaled by the caller: a 2-tick poke on a quiet 1m bar is
    tape noise, not a stop run.
    """
    if len(bars) < 6:
        return []
    n = len(bars)
    start = max(1, n - scan_bars)
    # One sweep vote per (direction, level): keep only the freshest occurrence
    # so repeated wicks at the same swing don't stack duplicate votes.
    latest: dict[tuple[Direction, float], StructureEvent] = {}

    for bi in range(start, n):
        bar = bars[bi]
        sl = [l for l in lows if l.index < bi]
        sh = [h for h in highs if h.index < bi]
        if sl:
            level = sl[-1].price
            if bar.low < level - min_depth and bar.close > level:
                latest[(Direction.LONG, level)] = StructureEvent(
                    StructureKind.SWEEP, Direction.LONG, level, bi, n - 1 - bi, tf)
        if sh:
            level = sh[-1].price
            if bar.high > level + min_depth and bar.close < level:
                latest[(Direction.SHORT, level)] = StructureEvent(
                    StructureKind.SWEEP, Direction.SHORT, level, bi, n - 1 - bi, tf)
    return list(latest.values())


def analyze_timeframe(bars: Sequence[Bar], timeframe: str,
                      strength: Optional[int] = None,
                      scan_bars: int = 10,
                      strict_choch: bool = True) -> TimeframeStructure:
    """Full structure read for one timeframe."""
    strength = strength or TF_STRENGTH.get(timeframe, 3)
    out = TimeframeStructure(timeframe=timeframe)
    if len(bars) < strength * 2 + 5:
        return out

    highs, lows = _swing_levels(bars, strength)
    if not highs or not lows:
        return out

    out.last_swing_high = highs[-1]
    out.last_swing_low = lows[-1]
    out.bias = classify_bias(highs, lows)
    out.protected_swing = _protected_swing(out.bias, highs, lows)

    a = atr(bars, 14)
    sweep_depth = max(1.0, 0.3 * a) if a else 1.0
    bos_choch = _detect_events(bars, highs, lows, out.bias, timeframe, scan_bars,
                               strict_choch=strict_choch)
    sweeps = _detect_sweeps(bars, highs, lows, timeframe, min(5, scan_bars),
                            min_depth=sweep_depth)
    all_ev = sorted(bos_choch + sweeps, key=lambda e: e.bar_index)
    out.events_recent = all_ev[-5:]
    out.last_event = all_ev[-1] if all_ev else None
    return out


@dataclass
class MultiTimeframeStructure:
    """HTF → LTF stack used for bias filter and entry triggers."""

    h1: TimeframeStructure = field(default_factory=lambda: TimeframeStructure("1h"))
    m15: TimeframeStructure = field(default_factory=lambda: TimeframeStructure("15m"))
    m5: TimeframeStructure = field(default_factory=lambda: TimeframeStructure("5m"))
    m1: TimeframeStructure = field(default_factory=lambda: TimeframeStructure("1m"))

    def htf_bias(self) -> Bias:
        """15m primary HTF; 1h confirms when available."""
        if self.h1.bias not in ("unknown", "ranging"):
            if self.m15.bias in ("unknown", "ranging") or self.m15.bias == self.h1.bias:
                return self.h1.bias
        return self.m15.bias

    def recent_event(self, tf: str, max_bars_ago: int = 12,
                     kinds: Optional[set[StructureKind]] = None) -> Optional[StructureEvent]:
        ts = {"1h": self.h1, "15m": self.m15, "5m": self.m5, "1m": self.m1}.get(tf)
        if ts is None or ts.last_event is None:
            return None
        ev = ts.last_event
        if ev.bars_ago > max_bars_ago:
            return None
        if kinds and ev.kind not in kinds:
            # scan recent list
            for e in reversed(ts.events_recent):
                if e.bars_ago <= max_bars_ago and (not kinds or e.kind in kinds):
                    return e
            return None
        return ev

    def to_dict(self) -> dict:
        return {
            "htf_bias": self.htf_bias(),
            "1h": self.h1.to_dict(),
            "15m": self.m15.to_dict(),
            "5m": self.m5.to_dict(),
            "1m": self.m1.to_dict(),
        }


def analyze_mtf(bars_1m: list[Bar], bars_5m: list[Bar],
                bars_15m: list[Bar], bars_1h: list[Bar],
                strict_choch: bool = True) -> MultiTimeframeStructure:
    return MultiTimeframeStructure(
        h1=analyze_timeframe(bars_1h, "1h", strict_choch=strict_choch),
        m15=analyze_timeframe(bars_15m, "15m", strict_choch=strict_choch),
        m5=analyze_timeframe(bars_5m, "5m", strict_choch=strict_choch),
        m1=analyze_timeframe(bars_1m, "1m", strict_choch=strict_choch),
    )
