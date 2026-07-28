"""gap (research/specs/gap.md): overnight-gap fade/continuation at the RTH
open — first registration of this family (Cycle 3). One candidate entry
per session; grid frozen at registration.
"""
from __future__ import annotations

import numpy as np

from app.research.families import common

FAMILY = "gap"
SPEC_ID = "gap-v1"
HYPOTHESIS = ("Moderate overnight gaps mean-revert toward the prior RTH "
              "close and large gaps continue away from it; conditioned on "
              "gap size in atr_5m units and entry delay, one arm clears the "
              "train gates net of costs despite the measured 09:30-10:00 "
              "drag — or gaps are decoration and the family closes.")

AXES = {
    "gmin": [0.5, 1.0, 2.0],          # |gap| >= gmin x atr_5m
    "gcap": [4.0, 999],               # |gap| <= gcap (999 = uncapped)
    "arm": ["fade", "go"],
    "delay": [1, 15, 30],             # bars after the 09:30 open bar
    "stop_s": [1.0, 2.0],             # x atr_5m at entry
    "target_r": [1.0, 2.0],
    "horizon": [60, 120],
}
PARAMS_GRID = AXES

COLUMNS = ["pdc_dist_atr", "atr_1m", "atr_5m", "rvol_1m", "minute_et"]

UNFILLED_FLOOR = 0.5                  # fixed blind (spec)
RTH_OPEN_MIN = 570


def make_build(prep=None):
    def build(data, p):
        masks, stops = {}, {}
        for sd, d in data.items():
            n = len(d.close)
            sig_l = np.zeros(n, bool)
            sig_s = np.zeros(n, bool)
            st = np.full(n, np.nan)
            pdc = d.f["pdc_dist_atr"]
            a5 = d.f["atr_5m"]
            rth = np.flatnonzero(d.minute_et >= RTH_OPEN_MIN)
            if len(rth):
                o = int(rth[0])
                gap = pdc[o]
                i = o + int(p["delay"])
                if (np.isfinite(gap) and p["gmin"] <= abs(gap) <= p["gcap"]
                        and i < n and np.isfinite(pdc[i])
                        and np.sign(pdc[i]) == np.sign(gap)
                        and abs(pdc[i]) >= UNFILLED_FLOOR * abs(gap)
                        and np.isfinite(a5[i])):
                    direction = -np.sign(gap) if p["arm"] == "fade" else np.sign(gap)
                    (sig_l if direction > 0 else sig_s)[i] = True
                    st[i] = p["stop_s"] * a5[i]
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
        return masks, stops, p["target_r"], p["horizon"], "rth"
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid(data, AXES, make_build())
