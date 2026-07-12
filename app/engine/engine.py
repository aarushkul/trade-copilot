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
from app.indicators.noise import NoiseBands
from app.indicators.structure import StructureKind, analyze_mtf
from app.feed.bars import BarBuilder
from app.indicators.core import VwapState, atr, ema, relative_volume, rsi
from app.models import Bar, Direction, Grade, Quote, Signal, Vote

TRADEABLE_PHASES = {Phase.OPEN_DRIVE, Phase.MORNING, Phase.LUNCH, Phase.AFTERNOON}

# Setups that can trigger a call; everything else (divergence, candlestick
# patterns, exhaustion, VWAP plays, level reactions, CHoCH/sweeps, raw
# momentum) only confirms/adds score - they never fire on their own.
#
# This list was cut down on 2026-07-07 against 22 sessions of real MNQ tape
# (net of costs, per-setup isolation + in-mix attribution): pullback and
# ict_bos were the only setups profitable in every tested configuration; ORB
# is kept on external evidence (Zarattini & Aziz, SSRN 4416622) as it fires
# rarely and is volume-gated. ict_choch/ict_sweep/vwap/vwap_fade/level/
# continuation/orb_fail/noise_mom all measured breakeven-to-negative as
# triggers and now vote confluence only.
# 2026-07-12 update from the 188-session out-of-sample verdict: ict_bos was
# the fitted carrier of the in-sample edge (-$1,792 OOS, negative in 3 of 4
# segments, 1-for-7 in the walk-forward) and is demoted to confluence-only.
# pullback/orb also measured negative OOS — no trigger has proven edge; the
# selectivity settings (a_grade_only, daily_signal_cap, window blocks) exist
# to minimize the measured per-entry toll while signals remain advisory.
TRIGGER_TAGS = {"pullback", "orb"}

# Advisory displacement note (NOT a setup): a 1m bar this far outside recent
# range/volume norms is a move the engine deliberately won't chase — the
# orb/continuation freshness caps skip bars this violent by design, and
# 2026-07-09 replays over 25 real sessions measured every "chase the big bar"
# trigger variant net negative (displacement-as-trigger PF 0.47). The note
# exists so the dashboard can say "seen it, standing aside on purpose"
# instead of appearing blind while 200+ points move.
DISPLACEMENT_ATR_MULT = 2.0     # bar range vs prior 1m ATR
DISPLACEMENT_MIN_PTS = 15.0     # ignore "2x ATR" on dead tape
DISPLACEMENT_MIN_RVOL = 2.0     # bar volume vs prior 20-bar average
DISPLACEMENT_NOTE_TTL_SEC = 600  # keep the note on screen this long

# Advisory levels-break note (NOT a setup): first touch of a prior-day/
# overnight level after an approach from distance, then a 1m close through.
# This was the ONLY pattern that survived the 2026-07-11 research program's
# data-doubling (PF 2.17, bootstrap-t 2.9 across 2019-2026 train) — but at
# ~10 events/year it failed the n>=150 gate and is UNVALIDATED, so it can
# never fire a call. It is surfaced as context for the discretionary trader.
LEVELS_BREAK_APPROACH_ATR1 = 5.0   # |close 30m before touch - level| >= this x atr_1m
LEVELS_BREAK_THROUGH_ATR5 = 0.25   # 1m close through the level by >= this x atr_5m
LEVELS_BREAK_WATCH_BARS = 15       # break must come within this many bars of touch
LEVELS_BREAK_NOTE_TTL_SEC = 900
LEVELS_BREAK_NAMES = ("PDH", "PDL", "PDC", "ONH", "ONL")


class SignalEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bars = BarBuilder()
        self.vwap = VwapState()
        self.levels = LevelTracker()
        self.noise = NoiseBands()
        self.breaker = CircuitBreaker(settings)
        # Instance copy so backtests can isolate a single setup's edge.
        self.trigger_tags = set(TRIGGER_TAGS)

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
        self._last_displacement: Optional[dict] = None  # advisory note, see above
        self._last_levels_break: Optional[dict] = None  # advisory note, see above
        self._lvl_watch: dict = {"day": "", "done": set(), "watch": {}}
        self._signals_day: tuple[str, int] = ("", 0)  # daily_signal_cap counter

    # -- warm-up ---------------------------------------------------------------

    def seed_history(self, minute_bars: list[Bar]) -> None:
        """Warm indicators, levels and VWAP from historical 1m bars."""
        self.bars.seed_from_minute_bars(minute_bars)
        for mb in minute_bars:
            self.levels.on_minute_bar(mb)
            self.noise.on_minute_bar(mb)
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
        # Book minute closes (VWAP, levels) before evaluating, so on-the-minute
        # evaluations see the bar that just closed rather than lagging it.
        for tf, bar in closed:
            if tf == "1m":
                self._on_minute_close(bar)
        evaluated = False
        for tf, bar in closed:
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
        self.noise.on_minute_bar(bar)
        self._note_displacement(bar)
        self._note_levels_break(bar)

    def _note_displacement(self, bar: Bar) -> None:
        """Flag an abnormal-range, high-volume 1m bar for the dashboard."""
        bars = self.bars.series["1m"].last_bars(30)
        if len(bars) < 22 or bars[-1].ts != bar.ts:
            return
        rng = bar.high - bar.low
        a = atr(bars[:-1], 14)          # vs the tape *before* this bar
        rv = relative_volume(bars, 20)  # this bar vs prior 20-bar average
        if a is None or a <= 0 or rv is None:
            return
        if (rng >= DISPLACEMENT_ATR_MULT * a and rng >= DISPLACEMENT_MIN_PTS
                and rv >= DISPLACEMENT_MIN_RVOL):
            self._last_displacement = {
                "ts": bar.ts,
                "points": round(rng, 2),
                "atr_mult": round(rng / a, 1),
                "rvol": round(rv, 1),
                "direction": "SELL" if bar.close < bar.open else "BUY",
            }

    def _note_levels_break(self, bar: Bar) -> None:
        """Advisory levels-break context (see LEVELS_BREAK_* above): first
        touch of PDH/PDL/PDC/ONH/ONL approached from >= 5x atr_1m away
        (30 min prior), then a 1m close through by >= 0.25x atr_5m within
        15 bars. Unvalidated (n=68 over 7 years) — never fires a call."""
        bars = self.bars.series["1m"].last_bars(40)
        if len(bars) < 32 or bars[-1].ts != bar.ts:
            return
        day = to_et(bar.ts).strftime("%Y-%m-%d")
        if self._lvl_watch["day"] != day:
            self._lvl_watch = {"day": day, "done": set(), "watch": {}}
        st = self._lvl_watch
        a1 = atr(bars[:-1], 14)
        a5 = atr(self.bars.series["5m"].last_bars(20), 14)
        if not a1 or not a5:
            return

        for name, px in self.levels.levels.named_levels():
            if name not in LEVELS_BREAK_NAMES or px is None or name in st["done"]:
                continue
            w = st["watch"].get(name)
            if w is None:
                if bar.low <= px <= bar.high:            # first touch today
                    approach = bars[-31].close
                    if abs(approach - px) >= LEVELS_BREAK_APPROACH_ATR1 * a1:
                        # origin = the side price came from; break goes the other way
                        st["watch"][name] = w = {
                            "bars": 0, "px": px,
                            "brk_dir": 1.0 if approach < px else -1.0}
                    else:
                        st["done"].add(name)             # touch without approach: spent
            if w is None:
                continue
            through = (bar.close - w["px"]) * w["brk_dir"]
            if through >= LEVELS_BREAK_THROUGH_ATR5 * a5:
                self._last_levels_break = {
                    "ts": bar.ts, "level": name, "px": round(w["px"], 2),
                    "direction": "BUY" if w["brk_dir"] > 0 else "SELL",
                    "through_pts": round(through, 2),
                }
                st["done"].add(name)
                st["watch"].pop(name, None)
                continue
            w["bars"] += 1
            if w["bars"] > LEVELS_BREAK_WATCH_BARS:      # no break: rejection, spent
                st["done"].add(name)
                st["watch"].pop(name, None)

    # -- evaluation ---------------------------------------------------------------

    def _build_context(self, q: Quote) -> MarketContext:
        b1m = self.bars.series["1m"].last_bars(120)
        b5m = self.bars.series["5m"].last_bars(60)
        b15m = self.bars.series["15m"].last_bars(40)
        b1h = self.bars.series["1h"].last_bars(48)
        closes_1m = [b.close for b in b1m]
        closes_5m = [b.close for b in b5m]
        structure = analyze_mtf(b1m, b5m, b15m, b1h,
                                strict_choch=self.settings.strict_choch)
        noise_bands = self.noise.bands_at(q.ts)
        return MarketContext(
            ts=q.ts, price=q.last,
            phase=phase_at(q.ts, self.settings.no_open_minutes,
                           self.settings.last_entry_minutes),
            bars_1m=b1m, bars_5m=b5m, bars_15m=b15m, bars_1h=b1h,
            structure=structure,
            vwap=self.vwap.vwap, vwap_sigma=self.vwap.sigma,
            ema9_1m=ema(closes_1m, 9), ema21_1m=ema(closes_1m, 21),
            ema9_5m=ema(closes_5m, 9), ema21_5m=ema(closes_5m, 21),
            rsi_1m=rsi(closes_1m, 14),
            atr_1m=atr(b1m, 14), atr_5m=atr(b5m, 14),
            rvol_1m=relative_volume(b1m, 20),
            levels=self.levels.levels,
            noise_lower=noise_bands[0] if noise_bands else None,
            noise_upper=noise_bands[1] if noise_bands else None,
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
                    sig_day = to_et(signal.ts).strftime("%Y-%m-%d")
                    self._signals_day = (
                        sig_day,
                        self._signals_day[1] + 1
                        if self._signals_day[0] == sig_day else 1)
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
        if (s.daily_signal_cap and self._signals_day[0] == day
                and self._signals_day[1] >= s.daily_signal_cap):
            return (f"daily cap: {self._signals_day[1]} signal(s) already today - "
                    "selectivity mode, every extra entry pays the toll")
        # CLOSED blocks regardless of rth_only: the journal force-flattens
        # anything open between 16:00-18:00 ET, so an entry there would be
        # flattened on the next quote (fire/flatten loop).
        if ctx.phase == Phase.CLOSED and not self.demo_override:
            return "market closed (16:00-18:00 ET / weekend) - no new entries"
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

    def _htf_allows(self, ctx: MarketContext, direction: Direction) -> bool:
        """ICT rule: don't fade 15m/1h bias without a recent CHoCH or sweep."""
        mtf = ctx.structure
        if mtf is None:
            return True
        htf = mtf.htf_bias()
        if htf in ("unknown", "ranging"):
            return True
        if (htf == "bullish" and direction == Direction.LONG) or \
           (htf == "bearish" and direction == Direction.SHORT):
            return True
        # Counter-HTF: need recent structural reversal permission.
        kinds = {StructureKind.CHOCH, StructureKind.SWEEP}
        for tf, ago in (("15m", 10), ("5m", 8), ("1h", 6)):
            ev = mtf.recent_event(tf, ago, kinds)
            if ev is not None and ev.direction == direction:
                return True
        return False

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
        if not self._htf_allows(ctx, direction):
            return None

        # Trend/VWAP bias alone is a filter, not a trade.
        # trigger setup (ORB, VWAP play, level reaction, pullback, continuation).
        triggers = [v for v in winning
                    if v.tag in self.trigger_tags and v.weight >= 1.0]
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

        if s.a_grade_only and grade != Grade.A:
            # Selectivity mode: B-grade confluence is context, never a call.
            return None
        if ctx.phase == Phase.LUNCH and s.lunch_a_grade_only and grade != Grade.A:
            return None
        return direction, grade, score, winning

    def _to_signal(self, ctx: MarketContext, direction: Direction, grade: Grade,
                   score: float, winning: list[Vote]) -> Optional[Signal]:
        if ctx.atr_5m is None:
            return None
        entry = ctx.price

        # Stop: beyond ICT protected swing on 1m when available, else recent 1m low/high.
        recent = ctx.bars_1m[-5:]
        if ctx.structure and ctx.structure.m1.protected_swing is not None:
            prot = ctx.structure.m1.protected_swing
            if direction == Direction.LONG:
                structural = max(entry - prot + 1.0, entry - (min(b.low for b in recent) - 1.0))
            else:
                structural = max(prot - entry + 1.0, (max(b.high for b in recent) + 1.0) - entry)
        elif direction == Direction.LONG:
            structural = entry - (min(b.low for b in recent) - 1.0)
        else:
            structural = (max(b.high for b in recent) + 1.0) - entry
        stop_points = max(structural, 1.0 * ctx.atr_5m)
        stop_points = min(max(stop_points, 5.0), 45.0)

        decision = build_trade_plan(direction, grade, entry, stop_points, self.settings)
        if decision.plan is None:
            return None
        plan = decision.plan

        triggers = [v for v in winning if v.tag in self.trigger_tags]
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

        disp = self._last_displacement
        if disp is not None and q.ts - disp["ts"] > DISPLACEMENT_NOTE_TTL_SEC:
            disp = None   # tape time, so replays age the note identically
        lvlbrk = self._last_levels_break
        if lvlbrk is not None and q.ts - lvlbrk["ts"] > LEVELS_BREAK_NOTE_TTL_SEC:
            lvlbrk = None
        state: dict = {
            "ts": q.ts,
            "price": q.last,
            "bid": q.bid,
            "ask": q.ask,
            "phase": phase_at(q.ts, self.settings.no_open_minutes,
                              self.settings.last_entry_minutes).value,
            "standing_aside": self._standing_aside,
            "displacement": disp,
            "levels_break": lvlbrk,
            "signals_today": self._signals_day[1] if self._signals_day[0] ==
            to_et(q.ts).strftime("%Y-%m-%d") else 0,
            "daily_signal_cap": self.settings.daily_signal_cap,
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
                "noise_lower": _r(ctx.noise_lower),
                "noise_upper": _r(ctx.noise_upper),
                "levels": ctx.levels.to_dict(),
                "chop": chop.is_chop if chop else False,
                "chop_detail": chop.detail if chop else "",
                "votes": [
                    {"direction": v.direction.value, "weight": v.weight,
                     "reason": v.reason, "tag": v.tag} for v in (votes or [])
                ],
                "structure": ctx.structure.to_dict() if ctx.structure else None,
            })
        self.on_state(state)


def _r(v: Optional[float]) -> Optional[float]:
    return round(v, 2) if v is not None else None
