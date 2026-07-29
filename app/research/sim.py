"""sim-1: the conservative fill/cost reference for all research results.

Pre-registered semantics (research/README.md; changing any of them bumps
SIM_VERSION and invalidates prior registrations):

- Rules see CLOSED 1m bars; a signal at bar i acts from bar i+1.
- Market entry: bar i+1 open +/- slippage_ticks against you.
- Stops and time exits are market fills (pay slippage); targets are resting
  limits that need a 1-tick trade-through (touch != fill), no slippage.
- Intra-bar path: up bar O->L->H->C, down bar O->H->L->C (same as
  replay.bar_to_quotes / powell._bar_path).
- Ambiguity rule: if one bar's range contains BOTH stop and target,
  score it a STOP regardless of path order.
- Force-flat at 15:59 ET; single bracket, one contract, one position at a time.
- Friction: 2 x commission_per_side per round trip.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from app.config import POINT_VALUE, TICK_SIZE
from app.models import Bar

SIM_VERSION = "sim-1"
ET = ZoneInfo("America/New_York")
COMMISSION_PER_SIDE = 0.74
SLIPPAGE_TICKS = 1
FLAT_MINUTE_ET = 15 * 60 + 59


@dataclass
class Trade:
    session: str
    direction: int            # +1 long, -1 short
    entry_i: int              # index of the FILL bar (signal bar + 1)
    entry_ts: float
    entry_px: float
    exit_ts: float
    exit_px: float
    exit_reason: str          # STOP | TARGET | HORIZON | FLAT
    stop_pts: float
    pnl_usd: float            # net of slippage (in px) and commissions
    r: float                  # pnl_usd / (stop_pts * POINT_VALUE)


def _minute_et(ts: float) -> int:
    dt = datetime.fromtimestamp(ts, tz=ET)
    return dt.hour * 60 + dt.minute


def _finalize(session: str, direction: int, entry_i: int, entry_ts: float,
              entry_px: float, exit_ts: float, exit_px: float, reason: str,
              stop_pts: float) -> Trade:
    pnl = (exit_px - entry_px) * direction * POINT_VALUE - 2 * COMMISSION_PER_SIDE
    return Trade(session, direction, entry_i, entry_ts, entry_px,
                 exit_ts, exit_px, reason, stop_pts, pnl,
                 pnl / (stop_pts * POINT_VALUE) if stop_pts > 0 else 0.0)


def resolve_bracket(bars: list[Bar], signal_i: int, direction: int,
                    stop_pts: float, target_pts: float, horizon_min: int | None,
                    session: str = "", slippage_ticks: int = SLIPPAGE_TICKS) -> Trade | None:
    """Resolve one bracket trade signalled at bars[signal_i] close.

    Returns None when no entry is possible (signal on the session's last bar
    or entry bar already at/after the force-flat minute).
    """
    entry_i = signal_i + 1
    if entry_i >= len(bars):
        return None
    eb = bars[entry_i]
    if _minute_et(eb.ts) >= FLAT_MINUTE_ET:
        return None
    slip = slippage_ticks * TICK_SIZE
    entry_px = eb.open + direction * slip
    stop_px = entry_px - direction * stop_pts
    target_px = entry_px + direction * target_pts

    for j in range(entry_i, len(bars)):
        b = bars[j]
        # force-flat first: at/after 15:59 nothing else may fill
        if _minute_et(b.ts) >= FLAT_MINUTE_ET:
            return _finalize(session, direction, entry_i, eb.ts, entry_px,
                             b.ts, b.open - direction * slip, "FLAT", stop_pts)
        if horizon_min is not None and j - entry_i >= horizon_min:
            return _finalize(session, direction, entry_i, eb.ts, entry_px,
                             b.ts, b.open - direction * slip, "HORIZON", stop_pts)

        if direction > 0:
            stop_touch = b.low <= stop_px
            tgt_fill = b.high >= target_px + TICK_SIZE   # trade-through
        else:
            stop_touch = b.high >= stop_px
            tgt_fill = b.low <= target_px - TICK_SIZE
        if stop_touch and tgt_fill:                       # ambiguity => STOP
            return _finalize(session, direction, entry_i, eb.ts, entry_px,
                             b.ts, stop_px - direction * slip, "STOP", stop_pts)
        if stop_touch:
            return _finalize(session, direction, entry_i, eb.ts, entry_px,
                             b.ts, stop_px - direction * slip, "STOP", stop_pts)
        if tgt_fill:
            return _finalize(session, direction, entry_i, eb.ts, entry_px,
                             b.ts, target_px, "TARGET", stop_pts)

    last = bars[-1]
    return _finalize(session, direction, entry_i, eb.ts, entry_px,
                     last.ts, last.close - direction * slip, "FLAT", stop_pts)


# --------------------------------------------------------------- sim-1.1
# Trailing-exit fill model (research/specs/trend_harvest.md). sim-1 above
# is untouched; registrations using trails record SIM_TRAIL_VERSION.

SIM_TRAIL_VERSION = "sim-1.1"


def resolve_trail(opens: np.ndarray, highs: np.ndarray, lows: np.ndarray,
                  closes: np.ndarray, ts: np.ndarray, minutes: np.ndarray,
                  signal_i: int, direction: int, stop_pts: float,
                  trail_pts: float, session: str = "",
                  slippage_ticks: float = SLIPPAGE_TICKS
                  ) -> tuple[Trade, int] | None:
    """One stop-only trade with a monotone ATR ratchet (spec sim-1.1).

    effective stop = max(initial, post-entry extreme of PRIOR closed bars
    − trail_pts) for longs (mirror shorts); trail_pts frozen at signal.
    Returns (trade, exit_bar_index) or None if no entry is possible.
    """
    entry_i = signal_i + 1
    n = len(opens)
    if entry_i >= n or minutes[entry_i] >= FLAT_MINUTE_ET:
        return None
    slip = slippage_ticks * TICK_SIZE
    entry_px = opens[entry_i] + direction * slip
    stop_px = entry_px - direction * stop_pts

    flat_hits = np.flatnonzero(minutes[entry_i:] >= FLAT_MINUTE_ET)
    flat_j = entry_i + int(flat_hits[0]) if len(flat_hits) else n
    o = opens[entry_i:flat_j]
    h = highs[entry_i:flat_j]
    lo = lows[entry_i:flat_j]

    if direction > 0:
        ext = np.maximum.accumulate(h)
        prior = np.concatenate(([-np.inf], ext[:-1]))
        eff = np.maximum(stop_px, prior - trail_pts)
        hit = lo <= eff
    else:
        ext = np.minimum.accumulate(lo)
        prior = np.concatenate(([np.inf], ext[:-1]))
        eff = np.minimum(stop_px, prior + trail_pts)
        hit = h >= eff
    hits = np.flatnonzero(hit)
    if len(hits):
        k = int(hits[0])
        j = entry_i + k
        level = float(eff[k])
        raw = min(o[k], level) if direction > 0 else max(o[k], level)
        px = raw - direction * slip
        reason = "TRAIL" if (direction > 0 and level > stop_px) or \
                            (direction < 0 and level < stop_px) else "STOP"
        return _finalize(session, direction, entry_i, ts[entry_i], entry_px,
                         ts[j], px, reason, stop_pts), j
    if flat_j < n:
        return _finalize(session, direction, entry_i, ts[entry_i], entry_px,
                         ts[flat_j], opens[flat_j] - direction * slip,
                         "FLAT", stop_pts), flat_j
    return _finalize(session, direction, entry_i, ts[entry_i], entry_px,
                     ts[n - 1], closes[n - 1] - direction * slip,
                     "FLAT", stop_pts), n - 1


def run_rule_trail(sessions: dict[str, list[Bar]],
                   masks: dict[str, tuple[np.ndarray, np.ndarray]],
                   stop_pts_by_session: dict[str, np.ndarray],
                   trail_pts_by_session: dict[str, np.ndarray],
                   window: tuple[int, int] = (570, 945),
                   slippage_ticks: float = SLIPPAGE_TICKS,
                   arrays: dict[str, tuple] | None = None) -> list[Trade]:
    """run_rule's skeleton with stop-only trailing exits (sim-1.1).

    `arrays` optionally supplies precomputed per-session
    (opens, highs, lows, closes, ts, minutes) to avoid rebuilding them
    on every grid point; contents must match `sessions` bar-for-bar.
    """
    trades: list[Trade] = []
    for sd, bars in sessions.items():
        if sd not in masks:
            continue
        long_m, short_m = masks[sd]
        stops = stop_pts_by_session[sd]
        trails = trail_pts_by_session[sd]
        n = len(bars)
        if arrays is not None and sd in arrays:
            opens, highs, lows, closes, ts, minutes = arrays[sd]
        else:
            opens = np.array([b.open for b in bars])
            highs = np.array([b.high for b in bars])
            lows = np.array([b.low for b in bars])
            closes = np.array([b.close for b in bars])
            ts = np.array([b.ts for b in bars])
            minutes = np.array([_minute_et(t) for t in ts])
        busy_until = -1
        for i in range(n - 1):
            if i <= busy_until:
                continue
            direction = 1 if long_m[i] else (-1 if short_m[i] else 0)
            if not direction:
                continue
            if not (window[0] <= minutes[i] <= window[1]):
                continue
            stop_pts = float(stops[i])
            trail_pts = float(trails[i])
            if not (np.isfinite(stop_pts) and stop_pts > 0
                    and np.isfinite(trail_pts) and trail_pts > 0):
                continue
            out = resolve_trail(opens, highs, lows, closes, ts, minutes,
                                i, direction, stop_pts, trail_pts,
                                session=sd, slippage_ticks=slippage_ticks)
            if out is None:
                continue
            tr, exit_j = out
            trades.append(tr)
            busy_until = exit_j
    return trades


FORWARD_PREFIX = "fwd_"


def assert_causal(columns: list[str]) -> None:
    """The fwd_* firewall: rule predicates may never see forward columns."""
    leaked = [c for c in columns if c.startswith(FORWARD_PREFIX)]
    if leaked:
        raise ValueError(f"rule references forward-looking columns: {leaked}")


def run_rule(sessions: dict[str, list[Bar]],
             masks: dict[str, tuple[np.ndarray, np.ndarray]],
             stop_pts_by_session: dict[str, np.ndarray],
             target_r: float, horizon_min: int | None,
             window: tuple[int, int] = (570, 945),  # 09:30..15:45 ET signal window
             slippage_ticks: int = SLIPPAGE_TICKS) -> list[Trade]:
    """Evaluate one rule variant. masks[sd] = (long_mask, short_mask) over
    that session's bars (True at SIGNAL bars); stop_pts_by_session[sd] gives
    the stop distance per signal bar (e.g. k * atr_5m). One position at a
    time, no re-entry until flat, entries only inside `window` (ET minutes).
    """
    trades: list[Trade] = []
    for sd, bars in sessions.items():
        if sd not in masks:
            continue
        long_m, short_m = masks[sd]
        stops = stop_pts_by_session[sd]
        busy_until = -1
        n = len(bars)
        for i in range(n - 1):
            if i <= busy_until:
                continue
            direction = 1 if long_m[i] else (-1 if short_m[i] else 0)
            if not direction:
                continue
            m = _minute_et(bars[i].ts)
            if not (window[0] <= m <= window[1]):
                continue
            stop_pts = float(stops[i])
            if not np.isfinite(stop_pts) or stop_pts <= 0:
                continue
            tr = resolve_bracket(bars, i, direction, stop_pts,
                                 stop_pts * target_r, horizon_min,
                                 session=sd, slippage_ticks=slippage_ticks)
            if tr is None:
                continue
            trades.append(tr)
            # occupied until the exit bar: find its index cheaply by time
            busy_until = i
            while busy_until < n - 1 and bars[busy_until].ts < tr.exit_ts:
                busy_until += 1
    return trades
