"""vol_regime (research/specs/vol_regime.md): ES-realized-vol conditioning
of the frozen trend-drift base block, under sim-1.1 trails. Cycle 4,
family 2. Grid frozen at registration.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from app.research.families import common
from app.research.families.xmkt import load_es_sessions
from app.research.sim import SIM_TRAIL_VERSION

FAMILY = "vol_regime"
SPEC_ID = "vol-regime-v1"
SIM_VERSION_OVERRIDE = SIM_TRAIL_VERSION
HYPOTHESIS = ("The trend_harvest drift is not uniform across volatility "
              "states: an external ES-realized-vol state concentrates it "
              "into high-vol regimes strongly enough to clear ALL gates "
              "including concentration — or vol states carry no "
              "conditioning information and both this family and the "
              "trend_harvest revival die together.")

AXES = {
    "N": [30, 60],
    "trail_k": [3.0, 4.0],
    "vol_k": [5, 20],
    "cond": ["low", "midhigh", "high"],
}
PARAMS_GRID = AXES

COLUMNS = ["atr_5m", "rvol_1m", "minute_et"]

# frozen base (spec): filt none, rvol_f 1.0, init_stop_s 2.0, cap 1, rth
RVOL_F = 1.0
INIT_STOP_S = 2.0
RTH_MIN, RTH_MAX = 570, 945
ES_RTH_MIN, ES_RTH_MAX = 570, 959
MIN_TRAIL_SESSIONS = 60
PCT_WINDOW = 252

_ET = ZoneInfo("America/New_York")


def _minute_et(ts: float) -> int:
    dt = datetime.fromtimestamp(ts, tz=_ET)
    return dt.hour * 60 + dt.minute


def es_parkinson_rv() -> dict[str, float]:
    """Per ES session: sqrt(mean(ln(high/low)^2)) over RTH minute bars."""
    out: dict[str, float] = {}
    for sd, bars in load_es_sessions().items():
        vals = []
        for ts, (h, lo) in bars.items():
            if ES_RTH_MIN <= _minute_et(ts) <= ES_RTH_MAX and h > lo > 0:
                vals.append(np.log(h / lo) ** 2)
        if vals:
            out[sd] = float(np.sqrt(np.mean(vals)))
    return out


def states_from_rv(dates: list[str], rv: dict[str, float],
                   k: int) -> dict[str, float]:
    """{session: percentile in [0,1]} — measure = mean rv of the k PRIOR
    sessions; percentile vs the trailing <=252 prior measures; sessions
    with < MIN_TRAIL_SESSIONS trailing measures get no state."""
    vals = [rv[d] for d in dates]
    measures: list[float] = []
    states: dict[str, float] = {}
    for i, d in enumerate(dates):
        m = float(np.mean(vals[i - k:i])) if i >= k else np.nan
        if np.isfinite(m):
            trail = [x for x in measures[-PCT_WINDOW:] if np.isfinite(x)]
            if len(trail) >= MIN_TRAIL_SESSIONS:
                states[d] = sum(1 for x in trail if x <= m) / len(trail)
        measures.append(m)
    return states


def _prep(data: dict[str, common.SessionData],
          states_by_k: dict[int, dict[str, float]] | None = None):
    if states_by_k is None:
        rv = es_parkinson_rv()
        dates = sorted(rv)
        states_by_k = {k: states_from_rv(dates, rv, k) for k in AXES["vol_k"]}
    per_n: dict[str, dict] = {}
    for sd, d in data.items():
        rth = (d.minute_et >= RTH_MIN) & (d.minute_et <= RTH_MAX)
        entry = {}
        for N in AXES["N"]:
            rmax = common.rolling_max(d.high, N)
            rmin = common.rolling_min(d.low, N)
            hi_prior = np.concatenate(([np.nan], rmax[:-1]))
            lo_prior = np.concatenate(([np.nan], rmin[:-1]))
            hi_prior[:N] = np.nan
            lo_prior[:N] = np.nan
            entry[N] = (hi_prior, lo_prior,
                        rth & np.isfinite(hi_prior) & (d.close > hi_prior),
                        rth & np.isfinite(lo_prior) & (d.close < lo_prior))
        per_n[sd] = entry
    return {"masks": per_n, "states": states_by_k}


def _in_state(pct: float, cond: str) -> bool:
    if cond == "high":
        return pct >= 2 / 3
    if cond == "midhigh":
        return pct >= 1 / 3
    return pct < 1 / 3


def make_build(prep):
    def build(data, p):
        masks, stops, trails = {}, {}, {}
        states = prep["states"][p["vol_k"]]
        for sd, d in data.items():
            n = len(d.close)
            sig_l = np.zeros(n, bool)
            sig_s = np.zeros(n, bool)
            st = np.full(n, np.nan)
            tp = np.full(n, np.nan)
            pct = states.get(sd)
            if pct is not None and _in_state(pct, p["cond"]):
                hi_prior, lo_prior, brk_l, brk_s = prep["masks"][sd][p["N"]]
                a5 = d.f["atr_5m"]
                rv_ = d.f["rvol_1m"]
                ok = np.isfinite(a5) & (rv_ >= RVOL_F)
                rearm = p["N"] // 2
                for cand, sig, prior, sign in (
                        (brk_l & ok, sig_l, hi_prior, 1),
                        (brk_s & ok, sig_s, lo_prior, -1)):
                    last = -10**9
                    for t in np.flatnonzero(cand):
                        if t < last + rearm:
                            continue
                        sp = (d.close[t] - prior[t]) * sign \
                            + INIT_STOP_S * a5[t]
                        if not np.isfinite(sp) or sp <= 0:
                            continue
                        sig[t] = True
                        st[t] = sp if np.isnan(st[t]) else min(st[t], sp)
                        tp[t] = p["trail_k"] * a5[t]
                        break                       # entries_cap = 1
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
            trails[sd] = tp
        return masks, stops, trails, "rth"
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid_trail(data, AXES, make_build(_prep(data)))
