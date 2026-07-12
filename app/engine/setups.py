"""Setup detectors. Each inspects the market context and casts weighted votes.

A vote is an opinion, not a trade. The engine only fires a call when enough
independent votes align (confluence) and risk rules allow it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.engine.session import Levels, Phase
from app.indicators.core import (
    double_top_bottom,
    is_bearish_engulfing,
    is_bearish_pin,
    is_bullish_engulfing,
    is_bullish_pin,
    rsi_divergence,
)
from app.indicators.structure import (
    MultiTimeframeStructure,
    StructureKind,
)
from app.models import Bar, Direction, Vote


@dataclass
class MarketContext:
    """Snapshot of everything the setups need, computed once per evaluation."""

    ts: float
    price: float
    phase: Phase
    bars_1m: list[Bar] = field(default_factory=list)
    bars_5m: list[Bar] = field(default_factory=list)
    bars_15m: list[Bar] = field(default_factory=list)
    bars_1h: list[Bar] = field(default_factory=list)
    structure: Optional[MultiTimeframeStructure] = None
    vwap: Optional[float] = None
    vwap_sigma: Optional[float] = None
    ema9_1m: Optional[float] = None
    ema21_1m: Optional[float] = None
    ema9_5m: Optional[float] = None
    ema21_5m: Optional[float] = None
    rsi_1m: Optional[float] = None
    atr_1m: Optional[float] = None
    atr_5m: Optional[float] = None
    rvol_1m: Optional[float] = None
    levels: Levels = field(default_factory=Levels)
    noise_lower: Optional[float] = None   # time-of-day noise band (see noise.py)
    noise_upper: Optional[float] = None

    def beyond_noise(self) -> Optional[Direction]:
        """Direction of abnormal displacement, None while inside the band."""
        if self.noise_upper is not None and self.price > self.noise_upper:
            return Direction.LONG
        if self.noise_lower is not None and self.price < self.noise_lower:
            return Direction.SHORT
        return None

    # -- trend helpers ---------------------------------------------------------

    def trend_1m(self) -> Optional[Direction]:
        if self.ema9_1m is None or self.ema21_1m is None:
            return None
        if self.ema9_1m > self.ema21_1m:
            return Direction.LONG
        if self.ema9_1m < self.ema21_1m:
            return Direction.SHORT
        return None

    def trend_5m(self) -> Optional[Direction]:
        if self.ema9_5m is None or self.ema21_5m is None:
            return None
        if self.ema9_5m > self.ema21_5m:
            return Direction.LONG
        if self.ema9_5m < self.ema21_5m:
            return Direction.SHORT
        return None

    def band(self, k: float) -> Optional[tuple[float, float]]:
        if self.vwap is None or self.vwap_sigma is None or self.vwap_sigma <= 0:
            return None
        return (self.vwap - k * self.vwap_sigma, self.vwap + k * self.vwap_sigma)


VOLUME_CONFIRM_RVOL = 1.5


def trend_bias(ctx: MarketContext) -> list[Vote]:
    """EMA structure on 1m/5m plus side of VWAP. The backbone bias votes."""
    votes: list[Vote] = []
    t1, t5 = ctx.trend_1m(), ctx.trend_5m()
    if t1 and t5 and t1 == t5:
        votes.append(Vote(t1, 1.5, f"1m and 5m EMA trend aligned {t1.value}",
                          "trend", is_trend_aligned=True))
    elif t5:
        votes.append(Vote(t5, 0.75, f"5m EMA trend {t5.value}", "trend",
                          is_trend_aligned=True))
    if ctx.vwap is not None:
        if ctx.price > ctx.vwap:
            votes.append(Vote(Direction.LONG, 0.5,
                              f"price above VWAP ({ctx.vwap:.2f})", "trend"))
        elif ctx.price < ctx.vwap:
            votes.append(Vote(Direction.SHORT, 0.5,
                              f"price below VWAP ({ctx.vwap:.2f})", "trend"))
    return votes


def opening_range(ctx: MarketContext) -> list[Vote]:
    """Opening range breakout / breakout-failure, mornings only."""
    votes: list[Vote] = []
    lv = ctx.levels
    if (not lv.opening_range_done or lv.opening_range_high is None
            or ctx.phase not in (Phase.OPEN_DRIVE, Phase.MORNING)
            or len(ctx.bars_1m) < 6):
        return votes

    orh, orl = lv.opening_range_high, lv.opening_range_low
    last = ctx.bars_1m[-1]
    vol_ok = ctx.rvol_1m is not None and ctx.rvol_1m >= VOLUME_CONFIRM_RVOL

    # Breakouts require volume confirmation and freshness (no chasing an
    # extended move 30+ points past the range).
    fresh = 12.0
    if last.close > orh and ctx.price > orh:
        if vol_ok and last.close - orh <= fresh:
            votes.append(Vote(Direction.LONG, 2.0,
                              f"1m close broke opening range high {orh:.2f} "
                              f"on {ctx.rvol_1m:.1f}x volume",
                              "orb", is_volume_confirmed=True))
    elif last.close < orl and ctx.price < orl:
        if vol_ok and orl - last.close <= fresh:
            votes.append(Vote(Direction.SHORT, 2.0,
                              f"1m close broke opening range low {orl:.2f} "
                              f"on {ctx.rvol_1m:.1f}x volume",
                              "orb", is_volume_confirmed=True))
    else:
        # Breakout failure: poked beyond the range recently, now back inside.
        recent = ctx.bars_1m[-4:]
        poked_high = any(b.high > orh for b in recent) and last.close < orh
        poked_low = any(b.low < orl for b in recent) and last.close > orl
        if poked_high and last.close < orh - 2:
            votes.append(Vote(Direction.SHORT, 1.5,
                              f"failed breakout above OR high {orh:.2f}, back inside",
                              "orb_fail"))
        elif poked_low and last.close > orl + 2:
            votes.append(Vote(Direction.LONG, 1.5,
                              f"failed breakdown below OR low {orl:.2f}, back inside",
                              "orb_fail"))
    return votes


def vwap_setups(ctx: MarketContext) -> list[Vote]:
    """VWAP reclaim/reject continuation and extreme-band mean reversion."""
    votes: list[Vote] = []
    if ctx.vwap is None or len(ctx.bars_1m) < 4:
        return votes
    b2, b1 = ctx.bars_1m[-2], ctx.bars_1m[-1]
    v = ctx.vwap

    # Reclaim: two consecutive 1m closes above VWAP after being below.
    if b2.close > v and b1.close > v and ctx.bars_1m[-3].close < v:
        vote = Vote(Direction.LONG, 1.5, f"VWAP reclaim, holding above {v:.2f}", "vwap")
        vote.is_trend_aligned = ctx.trend_5m() == Direction.LONG
        votes.append(vote)
    elif b2.close < v and b1.close < v and ctx.bars_1m[-3].close > v:
        vote = Vote(Direction.SHORT, 1.5, f"VWAP reject, holding below {v:.2f}", "vwap")
        vote.is_trend_aligned = ctx.trend_5m() == Direction.SHORT
        votes.append(vote)

    # Extreme band fades: need band touch + rejection candle + RSI extreme.
    # Regime gate: never fade while price is beyond the time-of-day noise band.
    # A +2σ VWAP stretch on a genuine trend day is trend, not "overdone" —
    # fading it is the classic way range traders donate money on trend days.
    bands2 = ctx.band(2.0)
    if bands2 and ctx.rsi_1m is not None and ctx.beyond_noise() is None:
        lo2, hi2 = bands2
        if b1.high >= hi2 and ctx.rsi_1m >= 70 and (
                is_bearish_pin(b1) or is_bearish_engulfing(b2, b1)):
            votes.append(Vote(Direction.SHORT, 1.5,
                              f"rejection at +2σ VWAP band ({hi2:.2f}), RSI {ctx.rsi_1m:.0f}",
                              "vwap_fade"))
        elif b1.low <= lo2 and ctx.rsi_1m <= 30 and (
                is_bullish_pin(b1) or is_bullish_engulfing(b2, b1)):
            votes.append(Vote(Direction.LONG, 1.5,
                              f"rejection at -2σ VWAP band ({lo2:.2f}), RSI {ctx.rsi_1m:.0f}",
                              "vwap_fade"))
    return votes


def key_levels(ctx: MarketContext) -> list[Vote]:
    """Reactions at PDH/PDL/PDC/ONH/ONL/OR levels."""
    votes: list[Vote] = []
    if len(ctx.bars_1m) < 3:
        return votes
    b2, b1 = ctx.bars_1m[-2], ctx.bars_1m[-1]
    near = 4.0  # points

    for name, level in ctx.levels.named_levels():
        # Rejection: wick pierced the level, closed back on the near side.
        if b1.high >= level - 1 and b1.close < level - 1 and \
                abs(b1.high - level) <= near and is_bearish_pin(b1):
            votes.append(Vote(Direction.SHORT, 1.25,
                              f"rejection wick at {name} {level:.2f}", "level"))
        elif b1.low <= level + 1 and b1.close > level + 1 and \
                abs(b1.low - level) <= near and is_bullish_pin(b1):
            votes.append(Vote(Direction.LONG, 1.25,
                              f"rejection wick at {name} {level:.2f}", "level"))
        # Break-and-hold: two closes beyond a level that is just behind price.
        elif b2.close > level and b1.close > level and 0 < b1.close - level <= 12 \
                and ctx.bars_1m[-3].close <= level:
            votes.append(Vote(Direction.LONG, 1.0,
                              f"broke and holding above {name} {level:.2f}", "level"))
        elif b2.close < level and b1.close < level and 0 < level - b1.close <= 12 \
                and ctx.bars_1m[-3].close >= level:
            votes.append(Vote(Direction.SHORT, 1.0,
                              f"broke and holding below {name} {level:.2f}", "level"))
    return votes


def ema_pullback(ctx: MarketContext) -> list[Vote]:
    """Trend pullback to the 1m 21-EMA with a reversal candle."""
    votes: list[Vote] = []
    if ctx.ema21_1m is None or len(ctx.bars_1m) < 3:
        return votes
    b2, b1 = ctx.bars_1m[-2], ctx.bars_1m[-1]
    t5 = ctx.trend_5m()
    touched = b1.low <= ctx.ema21_1m <= b1.high or b2.low <= ctx.ema21_1m <= b2.high

    # Quality filter: only take pullbacks on the right side of VWAP.
    if ctx.vwap is not None:
        if t5 == Direction.LONG and ctx.price < ctx.vwap:
            return votes
        if t5 == Direction.SHORT and ctx.price > ctx.vwap:
            return votes

    if t5 == Direction.LONG and touched and b1.close > ctx.ema21_1m and (
            is_bullish_pin(b1) or is_bullish_engulfing(b2, b1)):
        votes.append(Vote(Direction.LONG, 1.5,
                          f"pullback held 1m 21-EMA ({ctx.ema21_1m:.2f}) in 5m uptrend",
                          "pullback", is_trend_aligned=True))
    elif t5 == Direction.SHORT and touched and b1.close < ctx.ema21_1m and (
            is_bearish_pin(b1) or is_bearish_engulfing(b2, b1)):
        votes.append(Vote(Direction.SHORT, 1.5,
                          f"pullback rejected 1m 21-EMA ({ctx.ema21_1m:.2f}) in 5m downtrend",
                          "pullback", is_trend_aligned=True))
    return votes


def trend_continuation(ctx: MarketContext) -> list[Vote]:
    """Fresh push to new 30-minute highs/lows in the direction of the 5m trend."""
    votes: list[Vote] = []
    if len(ctx.bars_1m) < 32:
        return votes
    window = ctx.bars_1m[-31:-1]
    last = ctx.bars_1m[-1]
    t5 = ctx.trend_5m()
    vol_ok = ctx.rvol_1m is not None and ctx.rvol_1m >= 1.2
    hi30 = max(b.high for b in window)
    lo30 = min(b.low for b in window)

    if (t5 == Direction.LONG and last.close > hi30
            and last.close - hi30 <= 8 and vol_ok):
        votes.append(Vote(Direction.LONG, 1.5,
                          f"new 30-min high {last.close:.2f} with 5m uptrend",
                          "continuation", is_trend_aligned=True,
                          is_volume_confirmed=ctx.rvol_1m >= VOLUME_CONFIRM_RVOL))
    elif (t5 == Direction.SHORT and last.close < lo30
            and lo30 - last.close <= 8 and vol_ok):
        votes.append(Vote(Direction.SHORT, 1.5,
                          f"new 30-min low {last.close:.2f} with 5m downtrend",
                          "continuation", is_trend_aligned=True,
                          is_volume_confirmed=ctx.rvol_1m >= VOLUME_CONFIRM_RVOL))
    return votes


def momentum(ctx: MarketContext) -> list[Vote]:
    """RSI divergence reversals and overextension caution."""
    votes: list[Vote] = []
    if len(ctx.bars_1m) >= 30:
        div = rsi_divergence(ctx.bars_1m)
        if div == "bullish":
            votes.append(Vote(Direction.LONG, 1.25,
                              "bullish RSI divergence at recent lows", "divergence"))
        elif div == "bearish":
            votes.append(Vote(Direction.SHORT, 1.25,
                              "bearish RSI divergence at recent highs", "divergence"))
    # Overextension: price stretched beyond 2.5 sigma - vote against chasing.
    bands = ctx.band(2.5)
    if bands:
        lo, hi = bands
        if ctx.price > hi:
            votes.append(Vote(Direction.SHORT, 0.75,
                              "price stretched beyond +2.5σ of VWAP (exhaustion risk)",
                              "exhaustion"))
        elif ctx.price < lo:
            votes.append(Vote(Direction.LONG, 0.75,
                              "price stretched beyond -2.5σ of VWAP (exhaustion risk)",
                              "exhaustion"))
    return votes


def patterns(ctx: MarketContext) -> list[Vote]:
    """Standalone candlestick / chart patterns."""
    votes: list[Vote] = []
    if len(ctx.bars_1m) < 25:
        return votes
    b2, b1 = ctx.bars_1m[-2], ctx.bars_1m[-1]

    dtb = double_top_bottom(ctx.bars_1m[-40:] if len(ctx.bars_1m) >= 40 else ctx.bars_1m)
    if dtb == "top":
        votes.append(Vote(Direction.SHORT, 1.25, "double top forming on 1m", "pattern"))
    elif dtb == "bottom":
        votes.append(Vote(Direction.LONG, 1.25, "double bottom forming on 1m", "pattern"))

    if is_bullish_engulfing(b2, b1):
        votes.append(Vote(Direction.LONG, 0.5, "1m bullish engulfing", "pattern"))
    elif is_bearish_engulfing(b2, b1):
        votes.append(Vote(Direction.SHORT, 0.5, "1m bearish engulfing", "pattern"))
    return votes


def noise_momentum(ctx: MarketContext) -> list[Vote]:
    """Intraday momentum on a fresh break of the time-of-day noise band.

    Evidence: Zarattini/Barbon/Aziz (SSRN 4824172) — displacement beyond the
    average move-from-open for this minute of day marks abnormal demand or
    supply, and continuation (not reversion) follows on average. Freshness cap
    avoids chasing an extended trend leg far past the band.
    """
    votes: list[Vote] = []
    if (ctx.noise_upper is None or ctx.noise_lower is None
            or ctx.phase not in (Phase.OPEN_DRIVE, Phase.MORNING,
                                 Phase.LUNCH, Phase.AFTERNOON)
            or len(ctx.bars_1m) < 3):
        return votes
    last = ctx.bars_1m[-1]
    fresh = 12.0
    vol_ok = ctx.rvol_1m is not None and ctx.rvol_1m >= 1.1

    if last.close > ctx.noise_upper and 0 < last.close - ctx.noise_upper <= fresh \
            and vol_ok and ctx.trend_5m() != Direction.SHORT:
        votes.append(Vote(
            Direction.LONG, 2.0,
            f"1m close {last.close:.2f} broke above noise band "
            f"({ctx.noise_upper:.2f}) — abnormal buy imbalance for this time of day",
            "noise_mom", is_trend_aligned=ctx.trend_5m() == Direction.LONG,
            is_volume_confirmed=ctx.rvol_1m >= VOLUME_CONFIRM_RVOL))
    elif last.close < ctx.noise_lower and 0 < ctx.noise_lower - last.close <= fresh \
            and vol_ok and ctx.trend_5m() != Direction.LONG:
        votes.append(Vote(
            Direction.SHORT, 2.0,
            f"1m close {last.close:.2f} broke below noise band "
            f"({ctx.noise_lower:.2f}) — abnormal sell imbalance for this time of day",
            "noise_mom", is_trend_aligned=ctx.trend_5m() == Direction.SHORT,
            is_volume_confirmed=ctx.rvol_1m >= VOLUME_CONFIRM_RVOL))
    return votes


def ict_structure(ctx: MarketContext) -> list[Vote]:
    """Multi-timeframe BOS / CHoCH / liquidity sweep (ICT-style structure)."""
    votes: list[Vote] = []
    mtf = ctx.structure
    if mtf is None:
        return votes

    htf = mtf.htf_bias()

    # --- HTF bias confirmation (filter weight, not a standalone trigger) ---
    if htf == "bullish":
        votes.append(Vote(Direction.LONG, 0.75,
                          "15m/1h structure bullish (HH+HL)", "structure"))
    elif htf == "bearish":
        votes.append(Vote(Direction.SHORT, 0.75,
                          "15m/1h structure bearish (LH+LL)", "structure"))

    def _add_event(tf: str, max_ago: int, bos_w: float, choch_w: float, sweep_w: float) -> None:
        st = {"15m": mtf.m15, "5m": mtf.m5, "1m": mtf.m1, "1h": mtf.h1}[tf]
        for ev in reversed(st.events_recent):
            if ev.bars_ago > max_ago:
                continue
            aligned = htf in ("unknown", "ranging") or (
                (ev.direction == Direction.LONG and htf != "bearish")
                or (ev.direction == Direction.SHORT and htf != "bullish"))
            if ev.kind == StructureKind.BOS:
                w = bos_w if aligned else bos_w * 0.6
                votes.append(Vote(ev.direction, w,
                                  f"{tf} {ev.label()} ({ev.bars_ago} bars ago)",
                                  "ict_bos", is_trend_aligned=aligned))
            elif ev.kind == StructureKind.CHOCH:
                votes.append(Vote(ev.direction, choch_w,
                                  f"{tf} {ev.label()} — character shift ({ev.bars_ago} bars ago)",
                                  "ict_choch", is_trend_aligned=False))
            elif ev.kind == StructureKind.SWEEP:
                votes.append(Vote(ev.direction, sweep_w,
                                  f"{tf} liquidity sweep @ {ev.level:.2f} ({ev.bars_ago} bars ago)",
                                  "ict_sweep"))

    # HTF events: context (lower weight, longer memory)
    _add_event("1h", max_ago=6, bos_w=1.0, choch_w=1.25, sweep_w=1.0)
    _add_event("15m", max_ago=8, bos_w=1.25, choch_w=1.5, sweep_w=1.25)
    # Intermediate timeframe: triggers
    _add_event("5m", max_ago=6, bos_w=2.0, choch_w=1.75, sweep_w=1.75)
    # Entry timeframe: confirmation only (weights below the 1.0 trigger
    # threshold). Measured on real MNQ tape, raw 1m structure events churned
    # out hundreds of noise entries; the proper ICT entry is the MTF stack
    # below (5m break + 1m confirmation), which still triggers.
    _add_event("1m", max_ago=4, bos_w=0.9, choch_w=0.75, sweep_w=0.9)

    # Classic ICT sequence: HTF bias + 5m BOS/CHoCH + 1m BOS in same direction.
    ev5 = mtf.recent_event("5m", max_bars_ago=6,
                           kinds={StructureKind.BOS, StructureKind.CHOCH})
    ev1 = mtf.recent_event("1m", max_bars_ago=3, kinds={StructureKind.BOS})
    if ev5 and ev1 and ev5.direction == ev1.direction:
        d = ev5.direction
        if htf in ("unknown", "ranging") or (
                (d == Direction.LONG and htf != "bearish")
                or (d == Direction.SHORT and htf != "bullish")):
            votes.append(Vote(d, 1.5,
                              f"MTF stack: {ev5.kind.value} on 5m → BOS on 1m (aligned entry)",
                              "ict_bos", is_trend_aligned=True))

    return votes


ALL_SETUPS = [trend_bias, opening_range, vwap_setups, key_levels,
              ema_pullback, trend_continuation, noise_momentum,
              ict_structure, momentum, patterns]


def collect_votes(ctx: MarketContext) -> list[Vote]:
    votes: list[Vote] = []
    for setup in ALL_SETUPS:
        votes.extend(setup(ctx))
    return votes
