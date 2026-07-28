"""levels_v2 (research/specs/levels_v2.md): widened break-event universe —
prior-day/overnight levels plus prior-ISO-week extremes, 250-pt round
numbers, and initial-balance extremes; break arms only, first-`touch_n`
touch events per level. Grid frozen at registration.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from app.research.families import common

FAMILY = "levels_v2"
SPEC_ID = "levels-v2"
HYPOTHESIS = ("The v1 break mechanism (approach from distance -> first touch "
              "-> volume-backed close-through continues) is not specific to "
              "prior-day/overnight levels; on a wider universe of watched "
              "levels (prior-week extremes, 250-pt rounds, initial balance) "
              "and moderately lower approach floors it should clear n>=150 "
              "without diluting below the gates; if it dilutes, the v1 "
              "pattern is scale-specific dust and the family closes.")

AXES = {
    "levelset": ["daily", "weekly", "round", "full"],
    "approach": [2.5, 5.0, 10.0],     # x atr_1m, 30 bars before touch
    "arm": ["break25", "break50"],
    "touch_n": [1, 2],
    "window": ["rth", "w2", "w1"],
    "stop_s": [0.5, 1.0],
    "target_r": [1.0, 2.0],
}
PARAMS_GRID = AXES

COLUMNS = ["pdh_dist_atr", "pdl_dist_atr", "pdc_dist_atr", "onh_dist_atr",
           "onl_dist_atr", "atr_1m", "atr_5m", "rvol_1m", "minute_et"]

_DAILY = {"pdh", "pdl", "pdc", "onh", "onl"}
CLASS_SETS = {
    "daily": _DAILY,
    "weekly": _DAILY | {"pwh", "pwl"},
    "round": _DAILY | {"pwh", "pwl", "rn"},
    "full": _DAILY | {"pwh", "pwl", "rn", "ibh", "ibl"},
}
APPROACH_BARS = 30
BREAK_SEARCH_BARS = 15
RVOL_FLOOR = 1.2
RN_STEP = 250.0
IB_START, IB_END = 570, 630           # ET minutes; touches count from 630
IB_MIN_BARS = 45                      # "complete" IB = >=45 of 60 minutes


def _week(sd: str) -> tuple[int, int]:
    y, m, d = map(int, sd.split("-"))
    iso = date(y, m, d).isocalendar()
    return (iso[0], iso[1])


def _prior_week(sd: str) -> tuple[int, int]:
    y, m, d = map(int, sd.split("-"))
    iso = (date(y, m, d) - timedelta(days=7)).isocalendar()
    return (iso[0], iso[1])


def _touch_events(dist: np.ndarray, minute_et: np.ndarray,
                  min_minute: int) -> list[tuple[int, int]]:
    """All sign flips of dist, chronological, as (index, origin_side)."""
    sign = np.sign(dist)
    prev = np.concatenate(([np.nan], dist[:-1]))
    psign = np.sign(prev)
    flip = (np.isfinite(dist) & np.isfinite(prev)
            & (psign != sign) & (sign != 0) & (psign != 0))
    if min_minute:
        flip &= minute_et >= min_minute
    idx = np.flatnonzero(flip)
    return [(int(i), int(psign[i])) for i in idx]


def _prep(data: dict[str, common.SessionData]) -> dict[str, list]:
    """Per session: [(class, dist_in_points, touch_events)].

    dist = close - level for every class (v1 feature conventions: pdh/onh
    store (level-close)/atr5, the rest (close-level)/atr5). Prior-week
    hi/lo use only strictly-earlier sessions; round levels are constants
    enumerated from the realized range (causally neutral, see spec)."""
    week_hi: dict[tuple, float] = {}
    week_lo: dict[tuple, float] = {}
    for sd, d in data.items():
        wk = _week(sd)
        hi, lo = float(np.nanmax(d.high)), float(np.nanmin(d.low))
        week_hi[wk] = max(week_hi.get(wk, -math.inf), hi)
        week_lo[wk] = min(week_lo.get(wk, math.inf), lo)

    prep: dict[str, list] = {}
    for sd, d in data.items():
        a5 = d.f["atr_5m"]
        close = d.close
        raw: list[tuple[str, np.ndarray, int]] = [
            ("pdh", -d.f["pdh_dist_atr"] * a5, 0),
            ("pdl", d.f["pdl_dist_atr"] * a5, 0),
            ("pdc", d.f["pdc_dist_atr"] * a5, 0),
            ("onh", -d.f["onh_dist_atr"] * a5, 0),
            ("onl", d.f["onl_dist_atr"] * a5, 0),
        ]
        pw = _prior_week(sd)
        if pw in week_hi:
            raw.append(("pwh", close - week_hi[pw], 0))
            raw.append(("pwl", close - week_lo[pw], 0))
        lo, hi = float(np.nanmin(d.low)), float(np.nanmax(d.high))
        for k in range(math.ceil(lo / RN_STEP), math.floor(hi / RN_STEP) + 1):
            raw.append(("rn", close - k * RN_STEP, 0))
        ib = (d.minute_et >= IB_START) & (d.minute_et < IB_END)
        if int(ib.sum()) >= IB_MIN_BARS:
            raw.append(("ibh", close - float(np.max(d.high[ib])), IB_END))
            raw.append(("ibl", close - float(np.min(d.low[ib])), IB_END))
        prep[sd] = [(cls, dist, _touch_events(dist, d.minute_et, mm))
                    for cls, dist, mm in raw]
    return prep


def make_build(prep):
    def build(data, p):
        masks, stops = {}, {}
        arm_frac = {"break25": 0.25, "break50": 0.5}[p["arm"]]
        classes = CLASS_SETS[p["levelset"]]
        for sd, d in data.items():
            n = len(d.close)
            sig_l = np.zeros(n, bool)
            sig_s = np.zeros(n, bool)
            st = np.full(n, np.nan)
            a1 = d.f["atr_1m"]
            a5 = d.f["atr_5m"]
            rv = d.f["rvol_1m"]
            for cls, dist, events in prep[sd]:
                if cls not in classes:
                    continue
                examined = 0
                fired = False
                for i, origin in events:
                    if fired or examined >= p["touch_n"]:
                        break
                    examined += 1
                    back = i - APPROACH_BARS
                    if back < 0:
                        continue          # consumed: no approach lookback
                    ap = dist[back]
                    if not (np.isfinite(ap) and np.isfinite(a1[back])
                            and abs(ap) >= p["approach"] * a1[back]):
                        continue
                    for j in range(i, min(i + 1 + BREAK_SEARCH_BARS, n)):
                        if (np.isfinite(dist[j])
                                and np.sign(dist[j]) == -origin
                                and abs(dist[j]) >= arm_frac * a5[j]
                                and rv[j] >= RVOL_FLOOR):
                            sp = abs(dist[j]) + p["stop_s"] * a5[j]
                            if np.isfinite(sp):
                                (sig_l if -origin > 0 else sig_s)[j] = True
                                st[j] = sp if np.isnan(st[j]) else min(st[j], sp)
                                fired = True
                            break
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
        return masks, stops, p["target_r"], 60, p["window"]
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid(data, AXES, make_build(_prep(data)))
