"""compression (research/specs/compression.md): intraday coil breakout,
optionally NR-day conditioned — first registration of this family
(Cycle 3). Grid frozen at registration.
"""
from __future__ import annotations

import numpy as np

from app.research.families import common

FAMILY = "compression"
SPEC_ID = "compression-v1"
HYPOTHESIS = ("An m-bar trailing range unusually tight versus current "
              "volatility resolves with follow-through in the break "
              "direction, concentrated by a narrow-range prior session; "
              "if no arm clears the gates, compression is decoration on "
              "MNQ 1m at these costs and the family closes.")

AXES = {
    "nr_k": ["none", 4, 7],
    "m": [20, 40],
    "c": [1.5, 2.0, 3.0],             # coil <= c x atr_5m
    "break_b": [0.0, 0.5],            # close beyond coil by b x atr_1m
    "window": ["rth", "w2"],
    "stop_s": [0.5, 1.0],
    "target_r": [1.0, 2.0],
}
PARAMS_GRID = AXES

COLUMNS = ["atr_1m", "atr_5m", "rvol_1m", "minute_et"]

RVOL_FLOOR = 1.2
RTH_MIN, RTH_MAX = 570, 959           # 09:30..15:59 for NR-day ranges


def _rth_range(d: common.SessionData) -> float:
    m = (d.minute_et >= RTH_MIN) & (d.minute_et <= RTH_MAX)
    if not m.any():
        return float("nan")
    return float(np.max(d.high[m]) - np.min(d.low[m]))


def _prep(data: dict[str, common.SessionData]) -> dict[str, set]:
    """Per session: the set of nr_k values it qualifies for (prior session's
    RTH range narrowest of the last k prior sessions, strictly earlier)."""
    order = sorted(data)
    ranges = [_rth_range(data[sd]) for sd in order]
    nr: dict[str, set] = {}
    for i, sd in enumerate(order):
        ok = set()
        for k in (4, 7):
            if i >= k:
                window = ranges[i - k:i]          # last k priors
                prior = ranges[i - 1]
                if np.isfinite(prior) and all(np.isfinite(r) for r in window) \
                        and prior <= min(window):
                    ok.add(k)
        nr[sd] = ok
    return nr


def make_build(prep):
    coil_cache: dict[tuple, tuple] = {}

    def coil(sd: str, d: common.SessionData, m: int):
        key = (sd, m)
        if key not in coil_cache:
            rmax = common.rolling_max(d.high, m)
            rmin = common.rolling_min(d.low, m)
            cmax = np.concatenate(([np.nan], rmax[:-1]))   # bars [t-m, t-1]
            cmin = np.concatenate(([np.nan], rmin[:-1]))
            cmax[:m] = np.nan                              # need m full bars
            cmin[:m] = np.nan
            coil_cache[key] = (cmax, cmin)
        return coil_cache[key]

    def build(data, p):
        masks, stops = {}, {}
        for sd, d in data.items():
            n = len(d.close)
            sig_l = np.zeros(n, bool)
            sig_s = np.zeros(n, bool)
            st = np.full(n, np.nan)
            if p["nr_k"] == "none" or p["nr_k"] in prep[sd]:
                cmax, cmin = coil(sd, d, p["m"])
                a1, a5, rv = d.f["atr_1m"], d.f["atr_5m"], d.f["rvol_1m"]
                width = cmax - cmin
                compressed = width <= p["c"] * a5
                lng = d.close > cmax + p["break_b"] * a1
                sht = d.close < cmin - p["break_b"] * a1
                cand = (np.isfinite(width) & np.isfinite(a5) & np.isfinite(a1)
                        & compressed & (lng | sht) & (rv >= RVOL_FLOOR))
                last = -10**9
                for t in np.flatnonzero(cand):
                    if t < last + p["m"]:
                        continue                           # re-arm period
                    if lng[t]:
                        sp = d.close[t] - cmin[t] + p["stop_s"] * a5[t]
                        sig_l[t] = True
                    else:
                        sp = cmax[t] - d.close[t] + p["stop_s"] * a5[t]
                        sig_s[t] = True
                    st[t] = sp
                    last = int(t)
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
        return masks, stops, p["target_r"], 60, p["window"]
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid(data, AXES, make_build(_prep(data)))
