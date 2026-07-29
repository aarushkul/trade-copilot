"""trend_harvest (research/specs/trend_harvest.md): session-range breakout
entries under uncapped sim-1.1 trailing exits — the cycle-3 exit-structure
hypothesis. Grid frozen at registration.
"""
from __future__ import annotations

import numpy as np

from app.research.families import common
from app.research.sim import SIM_TRAIL_VERSION

FAMILY = "trend_harvest"
SPEC_ID = "trend-harvest-v1"
SIM_VERSION_OVERRIDE = SIM_TRAIL_VERSION
HYPOTHESIS = ("MNQ 1m P&L is a breakeven base plus rare trend-day outliers "
              "(cycle-3 meta-finding); every prior family capped exits at "
              "1-2R. Breakout entries are ~free; an uncapped ATR trailing "
              "stop riding trend legs to force-flat spreads the outlier "
              "days into enough medium wins to pass ALL gates including "
              "concentration — or the exit-structure hypothesis is dead "
              "and cycle 3 ends.")

AXES = {
    "N": [30, 60, 120],
    "filt": ["none", "ema"],
    "rvol_f": [1.0, 1.5],
    "trail_k": [2.0, 3.0, 4.0],       # x atr_5m at signal, frozen per trade
    "init_stop_s": [1.0, 2.0],        # x atr_5m buffer through the level
    "entries_cap": [1, 2],            # emitted signals per side per session
    "window": ["rth", "w2"],
}
PARAMS_GRID = AXES

COLUMNS = ["atr_5m", "rvol_1m", "ema21_5m_dist_atr", "minute_et"]

RTH_MIN, RTH_MAX = 570, 945           # emitted-signal bars (sim re-checks)


def _prep(data: dict[str, common.SessionData]) -> dict[str, dict]:
    """Per session per N: breakout candidate masks (vectorized, causal)."""
    prep: dict[str, dict] = {}
    for sd, d in data.items():
        n = len(d.close)
        rth = (d.minute_et >= RTH_MIN) & (d.minute_et <= RTH_MAX)
        per_n = {}
        for N in AXES["N"]:
            rmax = common.rolling_max(d.high, N)
            rmin = common.rolling_min(d.low, N)
            hi_prior = np.concatenate(([np.nan], rmax[:-1]))
            lo_prior = np.concatenate(([np.nan], rmin[:-1]))
            hi_prior[:N] = np.nan                 # need N full prior bars
            lo_prior[:N] = np.nan
            per_n[N] = (hi_prior, lo_prior,
                        rth & np.isfinite(hi_prior) & (d.close > hi_prior),
                        rth & np.isfinite(lo_prior) & (d.close < lo_prior))
        prep[sd] = per_n
    return prep


def make_build(prep):
    def build(data, p):
        masks, stops, trails = {}, {}, {}
        for sd, d in data.items():
            n = len(d.close)
            sig_l = np.zeros(n, bool)
            sig_s = np.zeros(n, bool)
            st = np.full(n, np.nan)
            tp = np.full(n, np.nan)
            hi_prior, lo_prior, brk_l, brk_s = prep[sd][p["N"]]
            a5 = d.f["atr_5m"]
            rv = d.f["rvol_1m"]
            ema = d.f["ema21_5m_dist_atr"]
            ok = np.isfinite(a5) & (rv >= p["rvol_f"])
            cand_l = brk_l & ok
            cand_s = brk_s & ok
            if p["filt"] == "ema":
                cand_l &= np.isfinite(ema) & (ema > 0)
                cand_s &= np.isfinite(ema) & (ema < 0)
            rearm = p["N"] // 2
            for cand, sig, prior, sign in ((cand_l, sig_l, hi_prior, 1),
                                           (cand_s, sig_s, lo_prior, -1)):
                emitted = 0
                last = -10**9
                for t in np.flatnonzero(cand):
                    if emitted >= p["entries_cap"] or t < last + rearm:
                        continue
                    sp = (d.close[t] - prior[t]) * sign \
                        + p["init_stop_s"] * a5[t]
                    if not np.isfinite(sp) or sp <= 0:
                        continue
                    sig[t] = True
                    st[t] = sp if np.isnan(st[t]) else min(st[t], sp)
                    tp[t] = p["trail_k"] * a5[t]
                    emitted += 1
                    last = int(t)
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
            trails[sd] = tp
        return masks, stops, trails, p["window"]
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid_trail(data, AXES, make_build(_prep(data)))
