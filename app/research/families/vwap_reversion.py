"""vwap_reversion (research/specs/vwap_reversion.md): fade pokes beyond
VWAP sigma-bands back toward VWAP, inside the noise band, unconditioned
(regime layer failed). Grid frozen at registration.
"""
from __future__ import annotations

import numpy as np

from app.research.families import common

FAMILY = "vwap_reversion"
SPEC_ID = "vwap_reversion-v1"
HYPOTHESIS = ("Pokes beyond VWAP +/- k sigma inside the noise band revert "
              "toward VWAP often enough to clear costs; if unconditioned "
              "fades fail train gates, the reversion edge does not exist at "
              "these costs.")

AXES = {
    "k": [1.5, 2.0, 2.5],
    "conf": ["none", "rejection", "rsi"],
    "stop_s": [0.5, 1.0],
    "target_r": [1.0, 1.5],
    "horizon": [60, 0],                 # 0 = run to force-flat
    "window": ["rth", "w1", "w2"],
}
PARAMS_GRID = AXES

COLUMNS = ["vwap_dist_sigma", "noise_pos", "rsi_1m", "atr_5m", "minute_et"]


def _prep(data: dict[str, common.SessionData]) -> dict[str, dict]:
    prep = {}
    for sd, d in data.items():
        prep[sd] = {
            "lo10": common.rolling_min(d.low, 10),
            "hi10": common.rolling_max(d.high, 10),
        }
    return prep


def make_build(prep):
    def build(data, p):
        masks, stops = {}, {}
        k = p["k"]
        for sd, d in data.items():
            vd = d.f["vwap_dist_sigma"]
            inside = np.abs(d.f["noise_pos"]) <= 1.0    # NaN -> False
            beyond_l = vd < -k
            beyond_s = vd > k
            prev_l = np.concatenate(([False], beyond_l[:-1]))
            prev_s = np.concatenate(([False], beyond_s[:-1]))
            if p["conf"] == "none":
                sig_l = beyond_l & ~prev_l
                sig_s = beyond_s & ~prev_s
            elif p["conf"] == "rejection":
                sig_l = prev_l & (vd >= -k)
                sig_s = prev_s & (vd <= k)
            else:                                        # rsi turn
                rsi = d.f["rsi_1m"]
                prev_rsi = np.concatenate(([50.0], rsi[:-1]))
                sig_l = beyond_l & ~prev_l & (rsi > prev_rsi)
                sig_s = beyond_s & ~prev_s & (rsi < prev_rsi)
            sig_l = sig_l & inside
            sig_s = sig_s & inside
            atr5 = d.f["atr_5m"]
            stop_l = d.close - prep[sd]["lo10"] + p["stop_s"] * atr5
            stop_s_ = prep[sd]["hi10"] - d.close + p["stop_s"] * atr5
            st = np.where(sig_l, stop_l, np.where(sig_s, stop_s_, np.nan))
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
        return masks, stops, p["target_r"], (p["horizon"] or None), p["window"]
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid(data, AXES, make_build(_prep(data)))
