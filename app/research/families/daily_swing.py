"""daily_swing (research/specs/daily_swing.md): multi-day momentum/
reversal under sim-2-daily (open-to-close-k-days-later, no intraday
stop). Cycle 4, family 4 — research-only label. Grid frozen at
registration. The tiny daily fill model and its gate loop live here;
golden tests in tests/test_research_families.py are part of the
registration.
"""
from __future__ import annotations

from statistics import median

import numpy as np

from app.config import POINT_VALUE, TICK_SIZE
from app.research import stats
from app.research.families import common
from app.research.sim import COMMISSION_PER_SIDE, SLIPPAGE_TICKS, Trade

FAMILY = "daily_swing"
SPEC_ID = "daily-swing-v1"
SIM_VERSION_OVERRIDE = "sim-2-daily"
HYPOTHESIS = ("Multi-day holding — where overnight gaps, the dominant "
              "component of multi-day index P&L, actually accrue — is the "
              "one horizon this corpus supports that was never tested: "
              "N-day closing-extreme momentum (or its reversal) carries "
              "expectancy at k-day holds net of costs, or the daily "
              "horizon is efficient too and cycle 4 ends.")

AXES = {
    "N": [5, 20],
    "hold": [1, 3, 5],
    "arm": ["mom", "rev"],
}
PARAMS_GRID = AXES

COLUMNS = ["minute_et"]

STOP_FLOOR = 5.0                      # r-normalization only (no real stop)


def daily_series(data: dict[str, common.SessionData]):
    """Sorted [(session, rth_open, rth_close, rth_range)] from the corpus."""
    rows = []
    for sd in sorted(data):
        d = data[sd]
        rth = np.flatnonzero((d.minute_et >= 570) & (d.minute_et <= 959))
        if not len(rth):
            continue
        o = float(d.open[rth[0]])
        c = float(d.close[rth[-1]])
        rng = float(np.max(d.high[rth]) - np.min(d.low[rth]))
        ts_open = float(d.bars[rth[0]].ts)
        ts_close = float(d.bars[rth[-1]].ts)
        rows.append((sd, o, c, rng, ts_open, ts_close))
    return rows


def run_daily(rows, p) -> list[Trade]:
    """sim-2-daily: signal on day t close -> enter t+1 open -> exit
    t+1+hold close. One position at a time; overlapping signals ignored."""
    slip = SLIPPAGE_TICKS * TICK_SIZE
    trades: list[Trade] = []
    closes = [r[2] for r in rows]
    busy_until = -1
    for t in range(len(rows)):
        if t <= busy_until or t < p["N"]:
            continue
        prior = closes[t - p["N"]:t]
        direction = 0
        if closes[t] > max(prior):
            direction = 1
        elif closes[t] < min(prior):
            direction = -1
        if not direction:
            continue
        if p["arm"] == "rev":
            direction = -direction
        ei, xi = t + 1, t + 1 + p["hold"]
        if xi >= len(rows):
            continue
        sd, eo, _, prev_rng = rows[ei][0], rows[ei][1], None, rows[t][3]
        entry_px = eo + direction * slip
        exit_px = rows[xi][2] - direction * slip
        pnl = (exit_px - entry_px) * direction * POINT_VALUE \
            - 2 * COMMISSION_PER_SIDE
        stop_pts = max(prev_rng, STOP_FLOOR)
        trades.append(Trade(sd, direction, ei, rows[ei][4], entry_px,
                            rows[xi][5], exit_px, "DAILY", stop_pts, pnl,
                            pnl / (stop_pts * POINT_VALUE)))
        busy_until = xi
    return trades


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    rows = daily_series(data)
    points = common.grid_points(AXES)
    out = []
    pf_by_key = {}
    for p in points:
        trades = run_daily(rows, p)
        m = stats.gate_metrics(trades)
        g = stats.train_gates(m, stress_pf=m.get("pf"))  # no slippage-stress
        m["stress_note"] = "no-stop model; stress gate = base pf"
        pf_by_key[common._key(p)] = m.get("pf", 0.0)
        out.append((p, m, g))
    for p, m, g in out:
        if not g["train_pass"]:
            continue
        neigh = [pf_by_key[common._key(q)]
                 for q in common._neighbors(p, AXES)
                 if common._key(q) in pf_by_key]
        med = median(neigh) if neigh else 0.0
        m["plateau_median_pf"] = round(med, 3)
        if med < 1.15:
            g["train_pass"] = False
            g["failed"] = g.get("failed", []) + ["plateau_median_pf>=1.15"]
    return out
