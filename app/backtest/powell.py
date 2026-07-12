"""Standalone backtest of the "Powell strategy" (TikTok ICT liquidity-sweep model).

The model (short side; long is the mirror):
  1. Liquidity: a confirmed swing high where stops rest.
  2. Sweep: wick takes the level out by an ATR-scaled depth, close reclaims
     back inside within `reclaim_bars` (sharp spike + rejection, not a clean
     breakout that keeps closing higher).
  3. Displacement + MSS: within `confirm_window` bars a full-bodied candle
     closes through the last swing low formed before the sweep.
  4. Entry: limit order on the retrace into the POI — 50% of the displacement
     leg, the displacement FVG (consequent encroachment), or the rejection
     block (sweep candle wick base).
  5. Stop just beyond the swept wick; target the opposing liquidity pool
     (prior swing low) or a fixed R multiple.

Fills are deliberately conservative: limit entries/targets must trade THROUGH
by one tick (a touch is not a fill), stop and time exits pay slippage_ticks,
every round trip pays 2x commission_per_side. Intrabar sequencing uses the
same O-H-L-C / O-L-H-C path assumption as app.backtest.replay so results are
comparable with the engine harness. One position or pending order at a time.

Usage:
    .venv/bin/python -m app.backtest.powell --file data/history/mnq_1m.json
    .venv/bin/python -m app.backtest.powell --file ... --grid   # sensitivity
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import POINT_VALUE, TICK_SIZE, TICK_VALUE, Settings
from app.models import Bar, Direction

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class PowellParams:
    swing_strength: int = 3        # fractal bars each side (1m, matches engine)
    pool_tf: str = "1m"            # liquidity map timeframe: 1m | 5m
    reclaim_bars: int = 2          # close back inside within N bars of the poke
    confirm_window: int = 10       # bars after sweep for displacement + MSS
    entry_window: int = 20         # bars the retrace limit order stays working
    disp_mode: str = "bar"         # bar: MSS candle itself | leg: whole move
    disp_body_atr: float = 1.0     # bar mode: MSS candle body >= k * ATR14
    disp_body_frac: float = 0.60   # ... and body >= 60% of its range
    disp_leg_atr: float = 2.0      # leg mode: sweep extreme -> MSS close >= k*ATR
    stop_buffer_ticks: int = 2     # stop beyond the swept wick
    entry_mode: str = "half"       # half | fvg | rb | mkt (no retrace: at MSS close)
    target_mode: str = "liq"       # liq | r
    target_r: float = 2.0          # used when target_mode == "r"
    min_rr: float = 1.0            # skip setups whose target is closer than this
    time_filter: str = "rth"       # all | rth | nyam
    bias_filter: bool = False      # require 15m swing bias to agree
    max_hold_bars: int = 180       # time stop
    flat_hour: int = 16            # force flat at 16:00 ET (app invariant)

    def label(self) -> str:
        bias = "+bias" if self.bias_filter else ""
        tgt = f"{self.target_r}R" if self.target_mode == "r" else "liq"
        return (f"{self.pool_tf}:{self.disp_mode}:{self.entry_mode}"
                f"/{tgt}/{self.time_filter}{bias}")


@dataclass
class Trade:
    direction: Direction
    signal_ts: float
    entry_ts: float = 0.0
    exit_ts: float = 0.0
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    exit_price: float = 0.0
    status: str = "PENDING"        # PENDING -> OPEN -> WIN/LOSS/FLAT/CANCELLED
    pool_level: float = 0.0        # swept liquidity level
    sweep_extreme: float = 0.0
    pnl_dollars: float = 0.0
    pnl_r: float = 0.0
    mae_points: float = 0.0
    mfe_points: float = 0.0


def _round_tick(p: float) -> float:
    return round(p / TICK_SIZE) * TICK_SIZE


def _bar_path(bar: Bar) -> list[float]:
    """Same intrabar assumption as replay.bar_to_quotes: up bar O-L-H-C."""
    if bar.close >= bar.open:
        return [bar.open, bar.low, bar.high, bar.close]
    return [bar.open, bar.high, bar.low, bar.close]


def _et(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=ET)


def _entries_allowed(ts: float, mode: str) -> bool:
    t = _et(ts)
    if t.weekday() >= 5:
        return False
    minutes = t.hour * 60 + t.minute
    if mode == "all":
        return not (16 * 60 <= minutes < 18 * 60)   # CLOSED phase, app invariant
    if mode == "rth":
        return 9 * 60 + 30 <= minutes < 15 * 60 + 45
    if mode == "nyam":
        return 9 * 60 + 30 <= minutes < 11 * 60 + 30
    raise ValueError(mode)


# ---------------------------------------------------------------------------
# Rolling market state: swings, ATR, 15m bias
# ---------------------------------------------------------------------------

class MarketState:
    """Incremental swings + ATR over the 1m series (no lookahead: a fractal
    swing with strength k only becomes visible k bars after its extreme)."""

    def __init__(self, params: PowellParams):
        self.p = params
        self.bars: list[Bar] = []
        self.swing_highs: list[tuple[int, float]] = []   # (1m bar index, price)
        self.swing_lows: list[tuple[int, float]] = []
        # 5m composite liquidity map: closed 5m bars + swings confirmed on close
        self.bars5: list[Bar] = []
        self._forming5: Optional[Bar] = None
        self.swing_highs5: list[tuple[int, float]] = []  # (confirm 1m idx, price)
        self.swing_lows5: list[tuple[int, float]] = []
        self.atr: Optional[float] = None
        self._trs: list[float] = []

    def _close_5m(self, confirm_idx: int) -> None:
        self.bars5.append(self._forming5)
        self._forming5 = None
        k = 2                            # TF_STRENGTH["5m"]
        c = len(self.bars5) - 1 - k
        if c >= k:
            seg = self.bars5[c - k:c + k + 1]
            cand = self.bars5[c]
            if all(cand.high >= b.high for b in seg):
                self.swing_highs5.append((confirm_idx, cand.high))
            if all(cand.low <= b.low for b in seg):
                self.swing_lows5.append((confirm_idx, cand.low))

    def push(self, bar: Bar) -> None:
        self.bars.append(bar)
        i = len(self.bars) - 1
        if i > 0:
            prev_close = self.bars[i - 1].close
            tr = max(bar.high - bar.low, abs(bar.high - prev_close),
                     abs(bar.low - prev_close))
            self._trs.append(tr)
            if len(self._trs) >= 14:
                window = self._trs[-14:]
                self.atr = sum(window) / 14
        # roll the 5m composite (a slot closes when a bar from a new slot arrives)
        slot = int(bar.ts // 300) * 300
        if self._forming5 is None:
            self._forming5 = Bar(slot, bar.open, bar.high, bar.low, bar.close)
        elif self._forming5.ts == slot:
            f = self._forming5
            f.high = max(f.high, bar.high)
            f.low = min(f.low, bar.low)
            f.close = bar.close
        else:
            self._close_5m(i)
            self._forming5 = Bar(slot, bar.open, bar.high, bar.low, bar.close)
        k = self.p.swing_strength
        c = i - k                       # candidate pivot, confirmed by bar i
        if c >= k:
            lo = c - k
            hi_seg = self.bars[lo:i + 1]
            cand = self.bars[c]
            if all(cand.high >= b.high for b in hi_seg):
                self.swing_highs.append((c, cand.high))
            if all(cand.low <= b.low for b in hi_seg):
                self.swing_lows.append((c, cand.low))

    def _pool_lists(self) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        if self.p.pool_tf == "5m":
            return self.swing_highs5, self.swing_lows5
        return self.swing_highs, self.swing_lows

    def last_swing_high_before(self, idx: int, pools: bool = False
                               ) -> Optional[tuple[int, float]]:
        src = self._pool_lists()[0] if pools else self.swing_highs
        for j in range(len(src) - 1, -1, -1):
            if src[j][0] < idx:
                return src[j]
        return None

    def last_swing_low_before(self, idx: int, pools: bool = False
                              ) -> Optional[tuple[int, float]]:
        src = self._pool_lists()[1] if pools else self.swing_lows
        for j in range(len(src) - 1, -1, -1):
            if src[j][0] < idx:
                return src[j]
        return None

    def opposing_pool(self, direction: Direction, beyond: float) -> Optional[float]:
        """Nearest older liquidity pool beyond `beyond` (target for the trade)."""
        highs, lows = self._pool_lists()
        pools = lows if direction == Direction.SHORT else highs
        for j in range(len(pools) - 1, -1, -1):
            price = pools[j][1]
            if direction == Direction.SHORT and price < beyond:
                return price
            if direction == Direction.LONG and price > beyond:
                return price
        return None

    def bias_15m(self) -> str:
        """HH+HL / LH+LL read on 15m composite swings (strength 2)."""
        bars15: list[Bar] = []
        for b in self.bars[-15 * 40:]:
            slot = int(b.ts // 900) * 900
            if bars15 and bars15[-1].ts == slot:
                bars15[-1].update(b.close)
                bars15[-1].high = max(bars15[-1].high, b.high)
                bars15[-1].low = min(bars15[-1].low, b.low)
            else:
                bars15.append(Bar(slot, b.open, b.high, b.low, b.close))
        k = 2
        highs: list[float] = []
        lows: list[float] = []
        for c in range(k, len(bars15) - k):
            seg = bars15[c - k:c + k + 1]
            if all(bars15[c].high >= x.high for x in seg):
                highs.append(bars15[c].high)
            if all(bars15[c].low <= x.low for x in seg):
                lows.append(bars15[c].low)
        if len(highs) < 2 or len(lows) < 2:
            return "unknown"
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            return "bullish"
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            return "bearish"
        return "ranging"


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

@dataclass
class _ArmedSweep:
    direction: Direction           # direction of the *trade* after the sweep
    pool_level: float
    sweep_extreme: float
    sweep_idx: int
    poke_idx: int
    mss_level: float               # structure that must break for confirmation
    deadline: int


class PowellBacktest:
    """measure_all=False: one pending order / position at a time (what a single
    trader could actually take). measure_all=True: every setup tracked
    independently in parallel — per-setup edge measurement, larger n."""

    def __init__(self, params: PowellParams, settings: Optional[Settings] = None,
                 measure_all: bool = False):
        self.p = params
        self.s = settings or Settings()
        self.measure_all = measure_all
        self.state = MarketState(params)
        self.trades: list[Trade] = []
        self.armed: list[_ArmedSweep] = []
        self.pending: list[tuple[Trade, int]] = []       # (order, expiry idx)
        self.open_trades: list[tuple[Trade, int]] = []   # (position, entry idx)
        self._consumed_pools: set[tuple[int, float]] = set()
        self._poked: dict[tuple[int, float], tuple[int, float, Direction]] = {}
        self.funnel = {"sweeps": 0, "mss": 0, "placed": 0, "filled": 0}

    # -- friction ------------------------------------------------------------

    def _finalize(self, t: Trade, status: str, exit_price: float, ts: float,
                  slip_exit: bool) -> None:
        sign = 1 if t.direction == Direction.LONG else -1
        px = exit_price - sign * self.s.slippage_ticks * TICK_SIZE if slip_exit \
            else exit_price
        gross = (px - t.entry) * sign * POINT_VALUE
        friction = 2 * self.s.commission_per_side          # limit in, 1 contract
        t.exit_price = px
        t.exit_ts = ts
        t.pnl_dollars = round(gross - friction, 2)
        risk = abs(t.entry - t.stop)
        t.pnl_r = round((px - t.entry) * sign / risk, 3) if risk > 0 else 0.0
        t.status = status
        self.trades.append(t)
        self.open_trades = [(x, k) for x, k in self.open_trades if x is not t]

    # -- sweep / MSS detection -------------------------------------------------

    def _detect_sweep(self, i: int) -> None:
        st = self.state
        bar = st.bars[i]
        depth = max(1.0, 0.3 * st.atr) if st.atr else 1.0

        for trade_dir in (Direction.SHORT, Direction.LONG):
            ref = st.last_swing_high_before(i, pools=True) \
                if trade_dir == Direction.SHORT \
                else st.last_swing_low_before(i, pools=True)
            if ref is None:
                continue
            pool_idx, level = ref
            key = (pool_idx, level)
            if key in self._consumed_pools:
                continue
            if trade_dir == Direction.SHORT:
                poked = bar.high > level + depth
                reclaimed = bar.close < level
            else:
                poked = bar.low < level - depth
                reclaimed = bar.close > level
            if poked and not reclaimed:
                prev = self._poked.get(key)
                ext = bar.high if trade_dir == Direction.SHORT else bar.low
                if prev:
                    first_pi = prev[0]
                    # Held beyond the level too long: that's a breakout, not a
                    # stop-run spike. Retire the pool.
                    if i - first_pi >= self.p.reclaim_bars:
                        self._consumed_pools.add(key)
                        del self._poked[key]
                        continue
                    ext = max(prev[1], ext) if trade_dir == Direction.SHORT \
                        else min(prev[1], ext)
                    self._poked[key] = (first_pi, ext, trade_dir)
                else:
                    self._poked[key] = (i, ext, trade_dir)
                continue
            sweep_extreme = None
            if poked and reclaimed:
                sweep_extreme = bar.high if trade_dir == Direction.SHORT else bar.low
                if key in self._poked:
                    prev_ext = self._poked[key][1]
                    sweep_extreme = max(prev_ext, sweep_extreme) \
                        if trade_dir == Direction.SHORT else min(prev_ext, sweep_extreme)
                    del self._poked[key]
            elif reclaimed and key in self._poked:
                pi, ext, _ = self._poked[key]
                if i - pi <= self.p.reclaim_bars:
                    sweep_extreme = ext
                del self._poked[key]
            if sweep_extreme is None:
                continue
            mss_ref = st.last_swing_low_before(i) if trade_dir == Direction.SHORT \
                else st.last_swing_high_before(i)
            if mss_ref is None:
                continue
            self._consumed_pools.add(key)
            self.funnel["sweeps"] += 1
            self.armed.append(_ArmedSweep(
                direction=trade_dir, pool_level=level, sweep_extreme=sweep_extreme,
                sweep_idx=i, poke_idx=i, mss_level=mss_ref[1],
                deadline=i + self.p.confirm_window))

    def _entry_price(self, arm: _ArmedSweep, mss_idx: int) -> Optional[float]:
        st = self.state
        bars = st.bars
        mss_bar = bars[mss_idx]
        if arm.direction == Direction.SHORT:
            leg_lo, leg_hi = mss_bar.low, arm.sweep_extreme
        else:
            leg_lo, leg_hi = arm.sweep_extreme, mss_bar.high

        if self.p.entry_mode == "half":
            return _round_tick((leg_lo + leg_hi) / 2)

        if self.p.entry_mode == "rb":
            sweep_bar = bars[arm.sweep_idx]
            if arm.direction == Direction.SHORT:
                base = max(sweep_bar.open, sweep_bar.close)
                return _round_tick(base) if sweep_bar.high > base else None
            base = min(sweep_bar.open, sweep_bar.close)
            return _round_tick(base) if sweep_bar.low < base else None

        if self.p.entry_mode == "fvg":
            # freshest imbalance inside the displacement leg
            for k in range(mss_idx - 1, arm.sweep_idx, -1):
                if k - 1 < 0 or k + 1 > mss_idx:
                    continue
                a, c = bars[k - 1], bars[k + 1]
                if arm.direction == Direction.SHORT and a.low > c.high:
                    return _round_tick((a.low + c.high) / 2)
                if arm.direction == Direction.LONG and a.high < c.low:
                    return _round_tick((a.high + c.low) / 2)
            return None
        raise ValueError(self.p.entry_mode)

    def _confirm_mss(self, i: int) -> None:
        st = self.state
        bar = st.bars[i]
        body = abs(bar.close - bar.open)
        rng = max(bar.high - bar.low, TICK_SIZE)
        bar_displaced = (st.atr is not None
                         and body >= self.p.disp_body_atr * st.atr
                         and body / rng >= self.p.disp_body_frac)

        still: list[_ArmedSweep] = []
        for arm in self.armed:
            if i > arm.deadline:
                continue                              # setup went stale
            if arm.direction == Direction.SHORT and bar.high > arm.sweep_extreme:
                continue                              # extreme violated pre-MSS
            if arm.direction == Direction.LONG and bar.low < arm.sweep_extreme:
                continue
            broke = (bar.close < arm.mss_level if arm.direction == Direction.SHORT
                     else bar.close > arm.mss_level)
            if self.p.disp_mode == "leg":
                leg = (arm.sweep_extreme - bar.close
                       if arm.direction == Direction.SHORT
                       else bar.close - arm.sweep_extreme)
                displaced = (st.atr is not None
                             and leg >= self.p.disp_leg_atr * st.atr)
            else:
                displaced = bar_displaced
            if not (broke and displaced):
                still.append(arm)
                continue
            self.funnel["mss"] += 1
            self._try_place(arm, i)
        self.armed = still

    def _try_place(self, arm: _ArmedSweep, mss_idx: int) -> None:
        if not self.measure_all and (self.pending or self.open_trades):
            return
        if not _entries_allowed(self.state.bars[mss_idx].ts, self.p.time_filter):
            return
        if self.p.bias_filter:
            bias = self.state.bias_15m()
            want = "bearish" if arm.direction == Direction.SHORT else "bullish"
            if bias != want:
                return

        mss_close = self.state.bars[mss_idx].close
        sign = 1 if arm.direction == Direction.LONG else -1
        if self.p.entry_mode == "mkt":
            # market order on the MSS close: pays entry slippage, no retrace wait
            entry = _round_tick(mss_close + sign * self.s.slippage_ticks * TICK_SIZE)
        else:
            entry = self._entry_price(arm, mss_idx)
            if entry is None:
                return
        buf = self.p.stop_buffer_ticks * TICK_SIZE
        stop = _round_tick(arm.sweep_extreme - sign * buf)
        risk = (entry - stop) * sign
        if risk <= 0:
            return

        mss_bar = self.state.bars[mss_idx]
        if self.p.target_mode == "r":
            target = _round_tick(entry + sign * self.p.target_r * risk)
        else:
            beyond = mss_bar.low if arm.direction == Direction.SHORT else mss_bar.high
            pool = self.state.opposing_pool(arm.direction, beyond)
            if pool is None:
                return
            target = _round_tick(pool - sign * 2 * TICK_SIZE)  # front-run the pool
            if (target - entry) * sign < self.p.min_rr * risk:
                return

        order = Trade(direction=arm.direction, signal_ts=mss_bar.ts,
                      entry=entry, stop=stop, target=target,
                      pool_level=arm.pool_level,
                      sweep_extreme=arm.sweep_extreme)
        self.funnel["placed"] += 1
        if self.p.entry_mode == "mkt":
            order.entry_ts = mss_bar.ts
            order.status = "OPEN"
            self.open_trades.append((order, mss_idx))
            self.funnel["filled"] += 1
        else:
            self.pending.append((order, mss_idx + self.p.entry_window))

    # -- order / position management -------------------------------------------

    def _cancel(self, t: Trade, reason: str = "EXPIRED") -> None:
        t.status = f"CANCELLED_{reason}"
        self.trades.append(t)

    def _work_pending(self, i: int) -> None:
        if not self.pending:
            return
        bar = self.state.bars[i]
        et = _et(bar.ts)
        no_new = et.hour >= self.p.flat_hour or (
            et.hour == self.p.flat_hour - 1 and et.minute >= 59)
        keep: list[tuple[Trade, int]] = []
        for t, expiry in self.pending:
            if i > expiry or no_new:
                self._cancel(t)
                continue
            resolved = False
            path = _bar_path(bar)
            for j in range(len(path) - 1):
                a, b = path[j], path[j + 1]
                lo, hi = min(a, b), max(a, b)
                # target touched before fill -> missed trade
                if (t.direction == Direction.SHORT and lo <= t.target) or \
                        (t.direction == Direction.LONG and hi >= t.target):
                    self._cancel(t, "TGT_FIRST")
                    resolved = True
                    break
                # limit fills only on trade-through by one tick
                through = t.entry + (TICK_SIZE if t.direction == Direction.SHORT
                                     else -TICK_SIZE)
                filled = (hi >= through if t.direction == Direction.SHORT
                          else lo <= through)
                if filled:
                    t.entry_ts = bar.ts
                    t.status = "OPEN"
                    self.open_trades.append((t, i))
                    self.funnel["filled"] += 1
                    # remaining path may hit the stop immediately
                    self._manage_open(t, i, path[j + 1:])
                    resolved = True
                    break
            if not resolved:
                keep.append((t, expiry))
        self.pending = keep

    def _manage_open(self, t: Trade, opened_idx: int,
                     path: Optional[list[float]] = None) -> None:
        i = len(self.state.bars) - 1
        bar = self.state.bars[i]
        sign = 1 if t.direction == Direction.LONG else -1
        seq = path if path is not None else _bar_path(bar)

        for j in range(len(seq)):
            px = seq[j]
            t.mfe_points = max(t.mfe_points, (px - t.entry) * sign)
            t.mae_points = max(t.mae_points, (t.entry - px) * sign)
            lo = min(seq[max(0, j - 1)], px)
            hi = max(seq[max(0, j - 1)], px)
            if (t.direction == Direction.LONG and lo <= t.stop) or \
                    (t.direction == Direction.SHORT and hi >= t.stop):
                self._finalize(t, "LOSS", t.stop, bar.ts, slip_exit=True)
                return
            through = t.target + (TICK_SIZE if t.direction == Direction.LONG
                                  else -TICK_SIZE)
            hit = (hi >= through if t.direction == Direction.LONG
                   else lo <= through)
            if hit:
                self._finalize(t, "WIN", t.target, bar.ts, slip_exit=False)
                return

        et = _et(bar.ts)
        flat_time = et.hour == self.p.flat_hour - 1 and et.minute >= 59
        if i - opened_idx >= self.p.max_hold_bars or flat_time \
                or et.hour == self.p.flat_hour:
            self._finalize(t, "FLAT", bar.close, bar.ts, slip_exit=True)

    # -- main loop ---------------------------------------------------------------

    def run(self, bars: list[Bar], warmup: int = 100) -> list[Trade]:
        for n, bar in enumerate(bars):
            self.state.push(bar)
            i = len(self.state.bars) - 1
            if n < warmup:
                continue
            for t, opened_idx in list(self.open_trades):
                self._manage_open(t, opened_idx)
            self._work_pending(i)
            if self.measure_all or not self.open_trades:
                self._confirm_mss(i)
                self._detect_sweep(i)
        last = self.state.bars[-1]
        for t, _ in list(self.open_trades):            # end of data
            self._finalize(t, "FLAT", last.close, last.ts, slip_exit=True)
        return self.trades


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def stats(trades: list[Trade]) -> dict:
    done = [t for t in trades if t.status in ("WIN", "LOSS", "FLAT")]
    if not done:
        return {"n": 0}
    pnls = [t.pnl_dollars for t in done]
    rs = [t.pnl_r for t in done]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    missed = sum(1 for t in trades if t.status == "CANCELLED_TGT_FIRST")
    gw, gl = sum(wins), -sum(losses)
    equity = peak = max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "n": len(done),
        "cancelled": sum(1 for t in trades if t.status.startswith("CANCELLED")),
        "missed_winners": missed,
        "win_rate": round(100 * len(wins) / len(done), 1),
        "avg_win": round(gw / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gl / len(losses), 2) if losses else 0.0,
        "expectancy": round(sum(pnls) / len(done), 2),
        "expectancy_r": round(sum(rs) / len(done), 3),
        "profit_factor": round(gw / gl, 2) if gl > 0 else None,
        "pnl": round(sum(pnls), 2),
        "max_dd": round(max_dd, 2),
    }


def half_split(trades: list[Trade]) -> tuple[dict, dict]:
    done = [t for t in trades if t.status in ("WIN", "LOSS", "FLAT")]
    mid = len(done) // 2
    return stats(done[:mid]), stats(done[mid:])


def run_variant(bars: list[Bar], params: PowellParams,
                measure_all: bool = False) -> tuple[dict, list[Trade], dict]:
    bt = PowellBacktest(params, measure_all=measure_all)
    trades = bt.run(bars)
    return stats(trades), trades, bt.funnel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/history/mnq_1m.json")
    ap.add_argument("--grid", action="store_true", help="run sensitivity grid")
    ap.add_argument("--entry", default="half",
                    choices=["half", "fvg", "rb", "mkt"])
    ap.add_argument("--target", default="liq", help="liq or an R multiple like 2.0")
    ap.add_argument("--filter", default="rth", choices=["all", "rth", "nyam"])
    ap.add_argument("--bias", action="store_true")
    ap.add_argument("--pool-tf", default="1m", choices=["1m", "5m"])
    ap.add_argument("--disp", default="bar", choices=["bar", "leg"])
    ap.add_argument("--measure-all", action="store_true",
                    help="track every setup independently (edge measurement) "
                         "instead of one position at a time")
    ap.add_argument("--dump-trades", default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    from app.backtest.replay import load_bars
    bars = load_bars(args.file)
    print(f"loaded {len(bars)} bars "
          f"({_et(bars[0].ts):%Y-%m-%d} .. {_et(bars[-1].ts):%Y-%m-%d} ET)")

    def build(entry: str, target: str, tf: str, bias: bool,
              pool_tf: str = "1m", disp: str = "bar") -> PowellParams:
        p = PowellParams(entry_mode=entry, time_filter=tf, bias_filter=bias,
                         pool_tf=pool_tf, disp_mode=disp)
        if target == "liq":
            p.target_mode = "liq"
        else:
            p.target_mode = "r"
            p.target_r = float(target)
        return p

    if not args.grid:
        p = build(args.entry, args.target, args.filter, args.bias,
                  args.pool_tf, args.disp)
        st, trades, funnel = run_variant(bars, p, measure_all=args.measure_all)
        h1, h2 = half_split(trades)
        print(f"\n=== Powell backtest [{p.label()}] ===")
        print(f"  funnel        : {funnel}")
        for k, v in st.items():
            print(f"  {k:<14}: {v}")
        print(f"  H1 PF {h1.get('profit_factor')} / H2 PF {h2.get('profit_factor')}"
              f"  (exp {h1.get('expectancy')} / {h2.get('expectancy')})")
        if args.dump_trades:
            rows = [t.__dict__ | {"direction": t.direction.value} for t in trades]
            Path(args.dump_trades).write_text(json.dumps(rows, indent=1, default=str))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(st, indent=2))
        return

    print(f"\n{'variant':<28}{'n':>5}{'win%':>7}{'exp$':>8}{'expR':>8}"
          f"{'PF':>6}{'P&L$':>9}{'maxDD$':>8}{'H1/H2 PF':>12}")
    results = {}
    for pool_tf in ("1m", "5m"):
        for disp in ("bar", "leg"):
            for tf in ("rth", "nyam", "all"):
                for entry in ("half", "fvg"):
                    for target in ("liq", "2.0"):
                        p = build(entry, target, tf, False, pool_tf, disp)
                        st, trades, _ = run_variant(bars, p, measure_all=True)
                        h1, h2 = half_split(trades)
                        results[p.label()] = st | {
                            "h1_pf": h1.get("profit_factor"),
                            "h2_pf": h2.get("profit_factor")}
                        if st["n"] == 0:
                            print(f"{p.label():<28}{'0':>5}")
                            continue
                        print(f"{p.label():<28}{st['n']:>5}{st['win_rate']:>7}"
                              f"{st['expectancy']:>8}{st['expectancy_r']:>8}"
                              f"{st['profit_factor'] or 'inf':>6}{st['pnl']:>9}"
                              f"{st['max_dd']:>8}"
                              f"{str(h1.get('profit_factor')) + '/' + str(h2.get('profit_factor')):>12}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
