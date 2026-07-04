"""The signal engine: turns the live bar stream into trade calls.

Wiring: feed -> BarBuilder -> SignalEngine.on_quote -> (state updates, signals)
Consumers subscribe via the on_state / on_signal callbacks.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from app.config import Settings
from app.engine.risk import CircuitBreaker, build_trade_plan
from app.engine.session import (
    ChopReport,
    LevelTracker,
    Phase,
    chop_filter,
    phase_at,
    session_date,
    to_et,
)
from app.engine.setups import MarketContext, collect_votes
from app.feed.bars import BarBuilder
from app.indicators.core import VwapState, atr, ema, relative_volume, rsi
from app.models import Bar, Direction, Grade, Quote, Signal, Vote

TRADEABLE_PHASES = {Phase.OPEN_DRIVE, Phase.MORNING, Phase.LUNCH, Phase.AFTERNOON}

# Setups that can trigger a call. Divergence, lone candlestick patterns and
# exhaustion stretches only confirm/add score - they never fire on their own.
TRIGGER_TAGS = {"orb", "orb_fail", "vwap", "vwap_fade", "level",
                "pullback", "continuation"}


class SignalEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bars = BarBuilder()
        self.vwap = VwapState()
        self.levels = LevelTracker()
        self.breaker = CircuitBreaker(settings)

        self.on_state: Optional[Callable[[dict], None]] = None
        self.on_signal: Optional[Callable[[Signal], None]] = None
        # Sim/demo feeds set this so signals fire outside market hours.
        self.demo_override = False

        self.last_quote: Optional[Quote] = None
        self.last_signal_ts: float = 0.0
        self.active_signal: Optional[Signal] = None   # set/cleared by the journal
        self._last_state_push = 0.0
        self._vwap_session: Optional[str] = None
        self._standing_aside: str = ""                # human reason, "" = able to trade

    # -- warm-up ---------------------------------------------------------------

    def seed_history(self, minute_bars: list[Bar]) -> None:
        """Warm indicators, levels and VWAP from historical 1m bars."""
        self.bars.seed_from_minute_bars(minute_bars)
        for mb in minute_bars:
            self.levels.on_minute_bar(mb)
        # Rebuild VWAP for the current session only.
        if minute_bars:
            cur = session_date(minute_bars[-1].ts)
            self._vwap_session = cur
            for mb in minute_bars:
                if session_date(mb.ts) == cur:
                    self.vwap.add_bar(mb)

    # -- live path ---------------------------------------------------------------

    def on_quote(self, q: Quote) -> None:
        self.last_quote = q
        closed = self.bars.on_quote(q)
        evaluated = False
        for tf, bar in closed:
            if tf == "1m":
                self._on_minute_close(bar)
            if tf == "15s":
                self._evaluate(q)
                evaluated = True
        if not evaluated:
            self._push_state(q, throttle=True)

    def _on_minute_close(self, bar: Bar) -> None:
        sess = session_date(bar.ts)
        if sess != self._vwap_session:
            self._vwap_session = sess
            self.vwap.reset()
        self.vwap.add_bar(bar)
        self.levels.on_minute_bar(bar)

    # -- evaluation ---------------------------------------------------------------

    def _build_context(self, q: Quote) -> MarketContext:
        b1m = self.bars.series["1m"].last_bars(120)
        b5m = self.bars.series["5m"].last_bars(60)
        b15m = self.bars.series["15m"].last_bars(40)
        closes_1m = [b.close for b in b1m]
        closes_5m = [b.close for b in b5m]
        return MarketContext(
            ts=q.ts, price=q.last,
            phase=phase_at(q.ts, self.settings.no_open_minutes,
                           self.settings.last_entry_minutes),
            bars_1m=b1m, bars_5m=b5m, bars_15m=b15m,
            vwap=self.vwap.vwap, vwap_sigma=self.vwap.sigma,
            ema9_1m=ema(closes_1m, 9), ema21_1m=ema(closes_1m, 21),
            ema9_5m=ema(closes_5m, 9), ema21_5m=ema(closes_5m, 21),
            rsi_1m=rsi(closes_1m, 14),
            atr_1m=atr(b1m, 14), atr_5m=atr(b5m, 14),
            rvol_1m=relative_volume(b1m, 20),
            levels=self.levels.levels,
        )

    def _evaluate(self, q: Quote) -> None:
        ctx = self._build_context(q)
        votes = collect_votes(ctx)
        chop = chop_filter(ctx.bars_1m, ctx.bars_5m)
        blocked = self._blocked_reason(ctx, chop)
        self._standing_aside = blocked or ""

        candidate = None
        if not blocked:
            candidate = self._score(ctx, votes)
            if candidate is not None:
                signal = self._to_signal(ctx, *candidate)
                if signal is not None:
                    self.last_signal_ts = signal.ts
                    if self.on_signal:
                        self.on_signal(signal)

        self._push_state(q, ctx=ctx, votes=votes, chop=chop)

    def _blocked_reason(self, ctx: MarketContext, chop: ChopReport) -> Optional[str]:
        s = self.settings
        day = to_et(ctx.ts).strftime("%Y-%m-%d")

        if len(ctx.bars_5m) < 22 or len(ctx.bars_1m) < 30:
            return "warming up indicators"
        if self.breaker.is_tripped(day):
            return (f"circuit breaker: {self.breaker.losses_today} stop-outs today - "
                    "done for the day, protect the account")
        if s.rth_only and not self.demo_override \
                and ctx.phase not in TRADEABLE_PHASES:
            return {
                Phase.OPEN_QUIET: "first minutes after the bell - letting the open settle",
                Phase.CLOSE: "too close to the session close for new entries",
                Phase.CLOSED: "market closed",
                Phase.PREMARKET: "pre-market - watching, not trading",
                Phase.OVERNIGHT: "overnight session - RTH-only mode",
            }.get(ctx.phase, "outside trading window")
        if chop.is_chop:
            return f"chop filter: {chop.detail}"
        if self.active_signal is not None:
            return f"managing open {self.active_signal.direction.value} signal"
        # Uses tape time (ctx.ts) so live and backtest behave identically.
        if ctx.ts - self.last_signal_ts < s.signal_cooldown_sec:
            remain = int(s.signal_cooldown_sec - (ctx.ts - self.last_signal_ts))
            return f"cooldown after last signal ({remain}s left)"
        return None

    def _score(self, ctx: MarketContext,
               votes: list[Vote]) -> Optional[tuple[Direction, Grade, float, list[Vote]]]:
        long_votes = [v for v in votes if v.direction == Direction.LONG]
        short_votes = [v for v in votes if v.direction == Direction.SHORT]
        long_score = sum(v.weight for v in long_votes)
        short_score = sum(v.weight for v in short_votes)

        if long_score >= short_score:
            direction, score, opposing, winning = (
                Direction.LONG, long_score, short_score, long_votes)
        else:
            direction, score, opposing, winning = (
                Direction.SHORT, short_score, long_score, short_votes)

        s = self.settings
        if score < s.score_fire_b or opposing > score * 0.5:
            return None

        # Trend/VWAP bias alone is a filter, not a trade. Require a concrete
        # trigger setup (ORB, VWAP play, level reaction, pullback, continuation).
        triggers = [v for v in winning
                    if v.tag in TRIGGER_TAGS and v.weight >= 1.0]
        if not triggers:
            return None

        trend_aligned = any(v.is_trend_aligned for v in winning)
        # Fading the 5m trend needs extra conviction: raise the bar for
        # counter-trend candidates instead of banning them outright.
        against_trend = (ctx.trend_5m() is not None
                         and ctx.trend_5m() != direction)
        if against_trend and score < s.score_fire_b + 1.0:
            return None
        volume_confirmed = (any(v.is_volume_confirmed for v in winning)
                            or (ctx.rvol_1m is not None and ctx.rvol_1m >= 1.8))
        if score >= s.score_fire_a and trend_aligned and volume_confirmed:
            grade = Grade.A
        else:
            grade = Grade.B

        if ctx.phase == Phase.LUNCH and s.lunch_a_grade_only and grade != Grade.A:
            return None
        return direction, grade, score, winning

    def _to_signal(self, ctx: MarketContext, direction: Direction, grade: Grade,
                   score: float, winning: list[Vote]) -> Optional[Signal]:
        if ctx.atr_5m is None:
            return None
        entry = ctx.price

        # Stop: beyond recent 1m structure, floored by ATR, hard bounds 5-45 pts.
        recent = ctx.bars_1m[-5:]
        if direction == Direction.LONG:
            structural = entry - (min(b.low for b in recent) - 1.0)
        else:
            structural = (max(b.high for b in recent) + 1.0) - entry
        stop_points = max(structural, 1.0 * ctx.atr_5m)
        stop_points = min(max(stop_points, 5.0), 45.0)

        decision = build_trade_plan(direction, grade, entry, stop_points, self.settings)
        if decision.plan is None:
            return None
        plan = decision.plan

        triggers = [v for v in winning if v.tag in TRIGGER_TAGS]
        setup_type = max(triggers or winning, key=lambda v: v.weight).tag
        reasons = [v.reason for v in sorted(winning, key=lambda v: -v.weight)]
        return Signal(
            direction=direction, grade=grade, score=score,
            entry=plan.entry, stop=plan.stop,
            target1=plan.target1, target2=plan.target2,
            contracts=plan.contracts, risk_dollars=plan.risk_dollars,
            setup_type=setup_type, reasons=reasons,
            ts=ctx.ts, expires_at=ctx.ts + self.settings.signal_ttl_sec,
        )

    # -- state broadcast --------------------------------------------------------------

    def _push_state(self, q: Quote, ctx: Optional[MarketContext] = None,
                    votes: Optional[list[Vote]] = None,
                    chop: Optional[ChopReport] = None, throttle: bool = False) -> None:
        if self.on_state is None:
            return
        now = time.time()
        if throttle and now - self._last_state_push < 1.0:
            return
        self._last_state_push = now

        state: dict = {
            "ts": q.ts,
            "price": q.last,
            "bid": q.bid,
            "ask": q.ask,
            "phase": phase_at(q.ts, self.settings.no_open_minutes,
                              self.settings.last_entry_minutes).value,
            "standing_aside": self._standing_aside,
            "breaker_losses": self.breaker.losses_today,
            "breaker_tripped": self.breaker.is_tripped(
                to_et(q.ts).strftime("%Y-%m-%d")),
        }
        if ctx is not None:
            state.update({
                "vwap": _r(ctx.vwap), "vwap_sigma": _r(ctx.vwap_sigma),
                "ema9_1m": _r(ctx.ema9_1m), "ema21_1m": _r(ctx.ema21_1m),
                "ema9_5m": _r(ctx.ema9_5m), "ema21_5m": _r(ctx.ema21_5m),
                "rsi_1m": _r(ctx.rsi_1m), "atr_1m": _r(ctx.atr_1m),
                "atr_5m": _r(ctx.atr_5m), "rvol_1m": _r(ctx.rvol_1m),
                "levels": ctx.levels.to_dict(),
                "chop": chop.is_chop if chop else False,
                "chop_detail": chop.detail if chop else "",
                "votes": [
                    {"direction": v.direction.value, "weight": v.weight,
                     "reason": v.reason, "tag": v.tag} for v in (votes or [])
                ],
            })
        self.on_state(state)


def _r(v: Optional[float]) -> Optional[float]:
    return round(v, 2) if v is not None else None
