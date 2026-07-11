"""trend_continuation (research/specs/trend_continuation.md + addendum):
pullbacks to EMA21/VWAP while price has held one side of VWAP for >= M
minutes with EMA slope agreement (structural trend condition — the regime
layer failed). Grid frozen at registration.
"""
from __future__ import annotations

import numpy as np

from app.research.families import common

FAMILY = "trend_continuation"
SPEC_ID = "trend_continuation-v1"
HYPOTHESIS = ("On structurally trending sessions the first pullbacks to "
              "dynamic support (EMA21/VWAP) hold and continue; if this "
              "cannot pass train gates, intraday trend-following does not "
              "clear retail costs on MNQ.")

AXES = {
    "side_min": [60, 120],
    "anchor": ["ema21", "vwap"],
    "depth": [0.25, 0.5],
    "rvol": [0.0, 1.0],
    "window": ["w2", "w1"],
    "stop_s": [0.25, 0.5],
    "target_r": [1.5, 2.0],
}
PARAMS_GRID = AXES

COLUMNS = ["vwap_dist_sigma", "vwap_side_min", "ema21_1m_slope",
           "ema21_1m_dist_atr", "atr_1m", "atr_5m", "sigma_pts",
           "ret_1m", "rvol_1m", "minute_et"]

MAX_PULLBACKS = 3


def _prep(data: dict[str, common.SessionData]) -> dict[str, dict]:
    prep = {}
    for sd, d in data.items():
        prep[sd] = {
            "lo10": common.rolling_min(d.low, 10),
            "hi10": common.rolling_max(d.high, 10),
            # anchor distance in POINTS, signed (close - anchor)
            "ema21": d.f["ema21_1m_dist_atr"] * d.f["atr_1m"],
            "vwap": d.f["vwap_dist_sigma"] * d.f["sigma_pts"],
        }
    return prep


def _episode_ok(pb: np.ndarray, max_n: int) -> np.ndarray:
    """True while inside one of the first max_n pullback episodes."""
    prev = np.concatenate(([False], pb[:-1]))
    starts = pb & ~prev
    return pb & (np.cumsum(starts) <= max_n)


def make_build(prep):
    def build(data, p):
        masks, stops = {}, {}
        for sd, d in data.items():
            f = d.f
            atr5 = f["atr_5m"]
            side = np.sign(f["vwap_dist_sigma"])
            held = f["vwap_side_min"] >= p["side_min"]
            slope_up = f["ema21_1m_slope"] > 0
            trend_l = held & (side > 0) & slope_up
            trend_s = held & (side < 0) & ~slope_up
            dist = prep[sd][p["anchor"]]              # close - anchor, points
            # pullback: near the anchor, not through it against trend
            pb_l = trend_l & (dist >= 0) & (dist <= p["depth"] * atr5)
            pb_s = trend_s & (dist <= 0) & (-dist <= p["depth"] * atr5)
            ok_l = _episode_ok(pb_l, MAX_PULLBACKS)
            ok_s = _episode_ok(pb_s, MAX_PULLBACKS)
            prev_l = np.concatenate(([False], ok_l[:-1]))
            prev_s = np.concatenate(([False], ok_s[:-1]))
            up = f["ret_1m"] > 0
            vol_ok = (f["rvol_1m"] >= p["rvol"]) if p["rvol"] > 0 else np.ones(len(atr5), bool)
            sig_l = prev_l & up & trend_l & (dist >= 0) & vol_ok
            sig_s = prev_s & ~up & trend_s & (dist <= 0) & vol_ok
            stop_l = d.close - prep[sd]["lo10"] + p["stop_s"] * atr5
            stop_s_ = prep[sd]["hi10"] - d.close + p["stop_s"] * atr5
            st = np.where(sig_l, stop_l, np.where(sig_s, stop_s_, np.nan))
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
        return masks, stops, p["target_r"], None, p["window"]
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid(data, AXES, make_build(_prep(data)))
