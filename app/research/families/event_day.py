"""event_day (research/specs/event_day.md): scheduled-macro reaction
continuation/fade under sim-1.1 trailing exits. Calendar frozen at
registration in research/specs/event_calendar.json. Cycle 4, family 1.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.research.families import common
from app.research.sim import SIM_TRAIL_VERSION

FAMILY = "event_day"
SPEC_ID = "event-day-v1"
SIM_VERSION_OVERRIDE = SIM_TRAIL_VERSION
HYPOTHESIS = ("Scheduled macro releases (FOMC 14:00, CPI/NFP 08:30) are the "
              "only scheduled candidates for the trend-day outliers where "
              "all measured MNQ profit lives; the initial reaction carries "
              "directional information (continuation or overreaction) that "
              "unconditional entries lack — or scheduled-event reactions "
              "are priced at 1m and the family closes.")

AXES = {
    "etype": ["fomc", "cpi_nfp", "all"],
    "arm": ["follow", "fade"],
    "delay": [1, 15, 30],
    "mv": [0.0, 1.0],                 # |reaction| >= mv x atr_5m[anchor2]
    "trail_k": [2.0, 3.0],
    "init_stop_s": [1.0, 2.0],
}
PARAMS_GRID = AXES

COLUMNS = ["atr_5m", "minute_et"]

CAL_PATH = Path(__file__).resolve().parents[3] / "research" / "specs" / \
    "event_calendar.json"
ANCHORS = {"fomc": (839, 854), "cpi_nfp": (509, 569)}   # ET minutes
WIN_LO, WIN_HI = 570, 945


def load_calendar(path: Path = CAL_PATH) -> dict[str, str]:
    """{session_date: etype}; CPI and NFP pool into cpi_nfp."""
    cal = json.loads(path.read_text())
    days: dict[str, str] = {}
    for d in cal["fomc"]:
        days[d] = "fomc"
    for k in ("cpi", "nfp"):
        for d in cal[k]:
            days[d] = "cpi_nfp"       # never collides with fomc in the data
    return days


def _prep(data: dict[str, common.SessionData],
          calendar: dict[str, str] | None = None) -> dict[str, list]:
    if calendar is None:
        calendar = load_calendar()
    prep: dict[str, list] = {}
    for sd, d in data.items():
        events = []
        et = calendar.get(sd)
        if et is not None:
            m1, m2 = ANCHORS[et]
            i1 = np.flatnonzero(d.minute_et == m1)
            i2 = np.flatnonzero(d.minute_et == m2)
            if len(i1) and len(i2):
                events.append((et, int(i1[0]), int(i2[0])))
        prep[sd] = events
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
            a5 = d.f["atr_5m"]
            for et, i1, i2 in prep[sd]:
                if p["etype"] != "all" and p["etype"] != et:
                    continue
                reaction = d.close[i2] - d.close[i1]
                if not np.isfinite(reaction) or reaction == 0:
                    continue
                if p["mv"] > 0 and not (np.isfinite(a5[i2])
                                        and abs(reaction) >= p["mv"] * a5[i2]):
                    continue
                sig = i2 + int(p["delay"])
                if sig >= n or not (WIN_LO <= d.minute_et[sig] <= WIN_HI):
                    continue
                if not np.isfinite(a5[sig]):
                    continue
                direction = int(np.sign(reaction))
                if p["arm"] == "fade":
                    direction = -direction
                (sig_l if direction > 0 else sig_s)[sig] = True
                sp = p["init_stop_s"] * a5[sig]
                st[sig] = sp if np.isnan(st[sig]) else min(st[sig], sp)
                tp[sig] = p["trail_k"] * a5[sig]
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
            trails[sd] = tp
        return masks, stops, trails, "rth"
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid_trail(data, AXES, make_build(_prep(data)))
