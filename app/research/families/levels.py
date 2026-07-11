"""levels (research/specs/levels.md + addendum): first touches of prior-day
and overnight levels after an approach from distance; fade and break arms
both unconditioned (regime layer failed). Grid frozen at registration.
"""
from __future__ import annotations

import numpy as np

from app.research.families import common

FAMILY = "levels"
SPEC_ID = "levels-v1"
HYPOTHESIS = ("First touches of PDH/PDL/PDC/ONH/ONL after an approach from "
              "distance produce tradeable reactions — rejection back toward "
              "the approach side or acceptance through; if neither arm "
              "passes train gates, levels are decoration.")

AXES = {
    "levelset": ["hl", "hlc", "all"],
    "approach": [5.0, 10.0],          # x atr_1m, measured 30 bars before touch
    "arm": ["fade1", "fade3", "break25", "break50"],
    "window": ["rth", "w1"],
    "stop_s": [0.5, 1.0],
    "target_r": [1.0, 2.0],
}
PARAMS_GRID = AXES

COLUMNS = ["pdh_dist_atr", "pdl_dist_atr", "pdc_dist_atr", "onh_dist_atr",
           "onl_dist_atr", "atr_1m", "atr_5m", "rvol_1m", "minute_et"]

LEVELSETS = {
    "hl": ["pdh", "pdl"],
    "hlc": ["pdh", "pdl", "pdc"],
    "all": ["pdh", "pdl", "pdc", "onh", "onl"],
}
APPROACH_BARS = 30
BREAK_SEARCH_BARS = 15


def _prep(data: dict[str, common.SessionData]) -> dict[str, dict]:
    """Signed distance close - level, in POINTS, per level per session.
    Feature conventions: pdh/onh distances are (level - close)/atr5;
    pdl/pdc/onl are (close - level)/atr5."""
    prep = {}
    for sd, d in data.items():
        a5 = d.f["atr_5m"]
        prep[sd] = {
            "pdh": -d.f["pdh_dist_atr"] * a5,
            "pdl": d.f["pdl_dist_atr"] * a5,
            "pdc": d.f["pdc_dist_atr"] * a5,
            "onh": -d.f["onh_dist_atr"] * a5,
            "onl": d.f["onl_dist_atr"] * a5,
        }
    return prep


def _first_touch(dist: np.ndarray) -> tuple[int, int]:
    """(index, origin_side) of the first sign flip; origin_side=-1 means the
    touch came from below. (-1, 0) when the level is never touched."""
    sign = np.sign(dist)
    valid = np.isfinite(dist)
    prev = np.concatenate(([np.nan], dist[:-1]))
    flip = valid & np.isfinite(prev) & (np.sign(prev) != sign) & (sign != 0) & (np.sign(prev) != 0)
    idx = np.flatnonzero(flip)
    if not len(idx):
        return -1, 0
    i = int(idx[0])
    return i, int(np.sign(prev[i]))


def make_build(prep):
    def build(data, p):
        masks, stops = {}, {}
        fade = p["arm"].startswith("fade")
        arm_n = {"fade1": 1, "fade3": 3, "break25": 0.25, "break50": 0.5}[p["arm"]]
        for sd, d in data.items():
            n = len(d.close)
            sig_l = np.zeros(n, bool)
            sig_s = np.zeros(n, bool)
            st = np.full(n, np.nan)
            a1 = d.f["atr_1m"]
            a5 = d.f["atr_5m"]
            for lv in LEVELSETS[p["levelset"]]:
                dist = prep[sd][lv]
                i, origin = _first_touch(dist)
                if i < APPROACH_BARS or origin == 0:
                    continue
                back = i - APPROACH_BARS
                ap = dist[back]
                if not (np.isfinite(ap) and np.isfinite(a1[back])
                        and abs(ap) >= p["approach"] * a1[back]):
                    continue
                if fade:
                    # close back on the origin side within arm_n bars
                    for j in range(i + 1, min(i + 1 + int(arm_n), n)):
                        if np.sign(dist[j]) == origin:
                            direction = origin       # back toward origin
                            sp = abs(dist[j]) + p["stop_s"] * a5[j]
                            if np.isfinite(sp):
                                (sig_l if direction > 0 else sig_s)[j] = True
                                st[j] = sp if np.isnan(st[j]) else min(st[j], sp)
                            break
                else:
                    # first close through by >= arm_n * atr5, rvol >= 1.2
                    for j in range(i, min(i + 1 + BREAK_SEARCH_BARS, n)):
                        thr = arm_n * a5[j]
                        if (np.isfinite(dist[j]) and np.sign(dist[j]) == -origin
                                and abs(dist[j]) >= thr
                                and d.f["rvol_1m"][j] >= 1.2):
                            direction = -origin      # continue through
                            sp = abs(dist[j]) + p["stop_s"] * a5[j]
                            if np.isfinite(sp):
                                (sig_l if direction > 0 else sig_s)[j] = True
                                st[j] = sp if np.isnan(st[j]) else min(st[j], sp)
                            break
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
        return masks, stops, p["target_r"], 60, p["window"]
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid(data, AXES, make_build(_prep(data)))
