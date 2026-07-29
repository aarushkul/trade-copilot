"""xmkt (research/specs/xmkt.md): ES→NQ divergence at RTH session extremes.
ES bars (data/history/xmkt_ES*.json, train window only) aligned to MNQ
bars by exact UTC minute. Grid frozen at registration.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from app.research.families import common

FAMILY = "xmkt"
SPEC_ID = "xmkt-v1"
HYPOTHESIS = ("ES and NQ are near-simultaneous at 1m but breadth structure "
              "is not arbitraged: a fresh ES RTH extreme that NQ has not "
              "confirmed for lag_k bars resolves by catch-up (follow) or "
              "rejection (fade); if neither arm clears the gates, "
              "cross-market price structure at >=1m granularity carries no "
              "MNQ edge at these costs and the family closes.")

AXES = {
    "b": [5, 15],
    "lag_k": [15, 30],
    "arm": ["follow", "fade"],
    "window": ["rth", "w2"],
    "stop_s": [0.5, 1.0],
    "target_r": [1.0, 2.0],
}
PARAMS_GRID = AXES

COLUMNS = ["atr_5m", "minute_et"]

RTH_MIN, RTH_MAX = 570, 959
NO_EXTREME_BOOT = 30                  # RTH bars before "no new high yet" arms

_ET = ZoneInfo("America/New_York")


def _session_key(ts: float) -> str:
    et = datetime.fromtimestamp(ts, tz=_ET)
    if et.hour >= 18:
        et += timedelta(days=1)
    return et.strftime("%Y-%m-%d")


def load_es_sessions() -> dict[str, dict[int, tuple[float, float]]]:
    """{session_date: {epoch_minute_ts: (high, low)}} from the pulled files."""
    from app.config import HISTORY_DIR
    out: dict[str, dict[int, tuple[float, float]]] = {}
    files = sorted(Path(HISTORY_DIR).glob("xmkt_ES*.json"))
    if not files:
        raise RuntimeError("no xmkt_ES*.json files — run pull_xmkt_es.py first")
    for f in files:
        for b in json.loads(f.read_text()):
            sd = _session_key(b["time"])
            out.setdefault(sd, {})[int(b["time"])] = (b["high"], b["low"])
    return out


def _new_extreme_series(high: np.ndarray, low: np.ndarray,
                        rth: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(new_high, new_low) booleans; the first RTH bar seeds the baseline
    and is NOT an event. NaN bars are never events and don't move the max."""
    n = len(high)
    nh = np.zeros(n, bool)
    nl = np.zeros(n, bool)
    hmax, lmin = np.nan, np.nan
    for t in range(n):
        if not rth[t]:
            continue
        h, lo = high[t], low[t]
        if np.isfinite(h):
            if np.isfinite(hmax) and h > hmax:
                nh[t] = True
            hmax = h if not np.isfinite(hmax) else max(hmax, h)
        if np.isfinite(lo):
            if np.isfinite(lmin) and lo < lmin:
                nl[t] = True
            lmin = lo if not np.isfinite(lmin) else min(lmin, lo)
    return nh, nl


def _prep(data: dict[str, common.SessionData],
          es_sessions: dict[str, dict[int, tuple[float, float]]] | None = None):
    """Per session: aligned ES arrays + extreme-event series for both mkts."""
    if es_sessions is None:
        es_sessions = load_es_sessions()
    prep = {}
    for sd, d in data.items():
        n = len(d.close)
        es_high = np.full(n, np.nan)
        es_low = np.full(n, np.nan)
        es = es_sessions.get(sd, {})
        for i, bar in enumerate(d.bars):
            hit = es.get(int(bar.ts))
            if hit is not None:
                es_high[i], es_low[i] = hit
        rth = (d.minute_et >= RTH_MIN) & (d.minute_et <= RTH_MAX)
        es_nh, es_nl = _new_extreme_series(es_high, es_low, rth)
        nq_nh, nq_nl = _new_extreme_series(d.high, d.low, rth)
        first_rth = int(np.flatnonzero(rth)[0]) if rth.any() else -1
        prep[sd] = {"rth": rth, "es_ok": np.isfinite(es_high),
                    "es_nh": es_nh, "es_nl": es_nl,
                    "nq_nh": nq_nh, "nq_nl": nq_nl, "first_rth": first_rth}
    return prep


def _last_true_idx(flags: np.ndarray) -> np.ndarray:
    """last_idx[t] = most recent u <= t with flags[u], else -1."""
    idx = np.where(flags, np.arange(len(flags)), -1)
    return np.maximum.accumulate(idx)


def make_build(prep):
    def build(data, p):
        masks, stops = {}, {}
        for sd, d in data.items():
            n = len(d.close)
            sig_l = np.zeros(n, bool)
            sig_s = np.zeros(n, bool)
            st = np.full(n, np.nan)
            pr = prep[sd]
            if pr["first_rth"] >= 0:
                a5 = d.f["atr_5m"]
                for side, es_flags, nq_flags in (
                        ("hi", pr["es_nh"], pr["nq_nh"]),
                        ("lo", pr["es_nl"], pr["nq_nl"])):
                    es_recent = common.rolling_max(
                        es_flags.astype(float), p["b"]) > 0
                    nq_last = _last_true_idx(nq_flags)
                    tarr = np.arange(n)
                    stale = np.where(
                        nq_last >= 0, tarr - nq_last >= p["lag_k"],
                        tarr >= pr["first_rth"] + NO_EXTREME_BOOT)
                    cand = (pr["rth"] & pr["es_ok"] & es_recent & stale
                            & np.isfinite(a5))
                    hits = np.flatnonzero(cand)
                    if len(hits):
                        t = int(hits[0])          # one signal per side
                        toward_high = (side == "hi")
                        go_long = toward_high if p["arm"] == "follow" \
                            else not toward_high
                        (sig_l if go_long else sig_s)[t] = True
                        sp = p["stop_s"] * a5[t]
                        st[t] = sp if np.isnan(st[t]) else min(st[t], sp)
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
        return masks, stops, p["target_r"], 60, p["window"]
    return build


def run(split: str, run_id: str | None = None):
    data = common.load_split(split, COLUMNS, run_id)
    return common.evaluate_grid(data, AXES, make_build(_prep(data)))
