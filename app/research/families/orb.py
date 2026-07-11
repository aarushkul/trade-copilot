"""orb (research/specs/orb.md): first 1m close beyond the opening range,
conditioned on freshness, relative volume and gap agreement (regime arm
collapsed to {any} — layer failed). Grid frozen at registration.
"""
from __future__ import annotations

import numpy as np

from app.research.families import common

FAMILY = "orb"
SPEC_ID = "orb-v1"
HYPOTHESIS = ("Unconditioned ORB is breakeven-at-best after costs; "
              "conditioned on elevated volume, freshness at the edge and "
              "gap agreement, first opening-range breaks carry "
              "follow-through.")

AXES = {
    "or_len": [5, 15, 30],
    "fresh": [0.25, 0.5],        # entry within fresh*atr5 of the OR edge
    "rvol": [1.0, 1.5],
    "gap": ["any", "side"],
    "cutoff": [660, 720],        # break before 11:00 / 12:00 ET
    "stop_s": [1.0, 1.5],        # vs opposite edge, whichever nearer
    "target_r": [1.0, 2.0],
}
PARAMS_GRID = AXES

COLUMNS = ["atr_5m", "rvol_1m", "gap_atr", "minute_et"]

RTH_OPEN = 570


def _prep(data: dict[str, common.SessionData]) -> dict[str, dict]:
    """OR high/low per session per length, from the bars."""
    prep = {}
    for sd, d in data.items():
        m = d.minute_et
        entry = {}
        for L in AXES["or_len"]:
            in_or = (m >= RTH_OPEN) & (m < RTH_OPEN + L)
            if not in_or.any():
                entry[L] = None
                continue
            entry[L] = (d.high[in_or].max(), d.low[in_or].min())
        prep[sd] = entry
    return prep


def make_build(prep):
    def build(data, p):
        masks, stops = {}, {}
        L = p["or_len"]
        for sd, d in data.items():
            n = len(d.close)
            sig_l = np.zeros(n, bool)
            sig_s = np.zeros(n, bool)
            st = np.full(n, np.nan)
            orhl = prep[sd].get(L)
            if orhl is not None:
                orh, orl = orhl
                m = d.minute_et
                atr5 = d.f["atr_5m"]
                live = (m >= RTH_OPEN + L) & (m < p["cutoff"])
                brk_l = live & (d.close > orh)
                brk_s = live & (d.close < orl)
                il = np.flatnonzero(brk_l)
                is_ = np.flatnonzero(brk_s)
                for i, isshort in ((il[0] if len(il) else -1, False),
                                   (is_[0] if len(is_) else -1, True)):
                    if i < 0:
                        continue
                    a5 = atr5[i]
                    if not np.isfinite(a5) or a5 <= 0:
                        continue
                    edge_dist = (d.close[i] - orh) if not isshort else (orl - d.close[i])
                    if edge_dist > p["fresh"] * a5:
                        continue                       # stale, chased break
                    if not (d.f["rvol_1m"][i] >= p["rvol"]):
                        continue
                    if p["gap"] == "side":
                        g = d.f["gap_atr"][i]
                        if not np.isfinite(g):
                            continue
                        if (not isshort and g < 0) or (isshort and g > 0):
                            continue
                    opp = (d.close[i] - orl) if not isshort else (orh - d.close[i])
                    sp = min(opp, p["stop_s"] * a5)
                    if isshort:
                        sig_s[i] = True
                    else:
                        sig_l[i] = True
                    st[i] = sp
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
        return masks, stops, p["target_r"], None, "rth"
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid(data, AXES, make_build(_prep(data)))
