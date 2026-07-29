"""onight (research/specs/onight.md): overnight-range breakout in the
European window under sim-1.1 trails. Cycle 4, family 3. Grid frozen at
registration.
"""
from __future__ import annotations

import numpy as np

from app.research.families import common
from app.research.sim import SIM_TRAIL_VERSION

FAMILY = "onight"
SPEC_ID = "onight-v1"
SIM_VERSION_OVERRIDE = SIM_TRAIL_VERSION
HYPOTHESIS = ("The 18:00-01:59 overnight range's first decisive, "
              "volume-backed break during the European hours (02:00-08:00 "
              "ET) carries follow-through ridden into the US day — or "
              "overnight structure is noise at these costs and the family "
              "closes.")

AXES = {
    "b": [0.0, 0.5],              # close beyond range by b x atr_1m
    "stop_s": [1.0, 2.0],         # buffer through the broken level
    "trail_k": [2.0, 3.0],        # x atr_5m frozen at signal
}
PARAMS_GRID = AXES

COLUMNS = ["atr_1m", "atr_5m", "rvol_1m", "minute_et"]

RVOL_FLOOR = 1.2
ON_MIN_BARS = 180
EU_LO, EU_HI = 120, 480


def _prep(data: dict[str, common.SessionData]) -> dict[str, tuple]:
    prep: dict[str, tuple] = {}
    for sd, d in data.items():
        on = (d.minute_et >= 1080) | (d.minute_et < EU_LO)
        if int(on.sum()) >= ON_MIN_BARS:
            prep[sd] = (float(np.max(d.high[on])), float(np.min(d.low[on])))
        else:
            prep[sd] = (np.nan, np.nan)
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
            onh, onl = prep[sd]
            if np.isfinite(onh) and np.isfinite(onl):
                a1, a5, rv = d.f["atr_1m"], d.f["atr_5m"], d.f["rvol_1m"]
                eu = (d.minute_et >= EU_LO) & (d.minute_et <= EU_HI)
                ok = eu & np.isfinite(a1) & np.isfinite(a5) & (rv >= RVOL_FLOOR)
                for level, cand, sig, sign in (
                        (onh, ok & (d.close > onh + p["b"] * a1), sig_l, 1),
                        (onl, ok & (d.close < onl - p["b"] * a1), sig_s, -1)):
                    hits = np.flatnonzero(cand)
                    if len(hits):
                        t = int(hits[0])              # cap 1 per side
                        sp = (d.close[t] - level) * sign + p["stop_s"] * a5[t]
                        if np.isfinite(sp) and sp > 0:
                            sig[t] = True
                            st[t] = sp if np.isnan(st[t]) else min(st[t], sp)
                            tp[t] = p["trail_k"] * a5[t]
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
            trails[sd] = tp
        return masks, stops, trails, "eu"
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid_trail(data, AXES, make_build(_prep(data)))
