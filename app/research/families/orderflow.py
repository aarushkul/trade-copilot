"""orderflow rule family (research/specs/orderflow.md + addendum): NQ
tick-rule proxy flow driving MNQ brackets. Three sub-grids evaluated
separately (plateau within each): absorption_fade, delta_break_confirm,
divergence_reversal. Coverage: flow-covered sessions only (2025 train year).
"""
from __future__ import annotations

import numpy as np

from app.research.families import common

FAMILY = "orderflow"
SPEC_ID = "orderflow-v1"
HYPOTHESIS = ("Per-minute NQ aggressor-flow proxy aggregates (delta, "
              "imbalance, absorption, divergence) carry exploitable signal "
              "for MNQ brackets at 30-60m horizons after retail costs; if "
              "no sub-grid passes train gates, retail-timescale order flow "
              "is dead for this program (scoped: 1s tick-rule proxy, 2025).")

SUBGRIDS = {
    "absorption_fade": {
        "imb": [0.15, 0.25],
        "stop_s": [0.5, 1.0],
        "target_r": [1.0, 1.5],
        "window": ["rth", "w1"],
    },
    "delta_break_confirm": {
        "imb": [0.2, 0.3],
        "stop_s": [1.0, 1.5],
        "target_r": [1.0, 2.0],
        "window": ["rth"],
    },
    "divergence_reversal": {
        "imb": [0.1, 0.2],
        "stop_s": [0.5, 1.0],
        "target_r": [1.0, 1.5],
        "window": ["rth", "w1"],
    },
}
PARAMS_GRID = SUBGRIDS
AXES = None  # runner prints via report()

COLUMNS = ["atr_5m", "minute_et"]
BREAK_CUTOFF_MIN = 720
HORIZON = 60


def _prep(data, flow_by_session):
    prep = {}
    for sd, d in data.items():
        fl = flow_by_session.get(sd)
        if fl is None or len(fl) != len(d.bars):
            continue
        import pandas as pd
        lo_inc = pd.Series(d.low).rolling(30, min_periods=5).min().to_numpy()
        hi_inc = pd.Series(d.high).rolling(30, min_periods=5).max().to_numpy()
        lo_prev = np.concatenate(([np.nan], lo_inc[:-1]))
        hi_prev = np.concatenate(([np.nan], hi_inc[:-1]))
        prep[sd] = {
            "lo_inc": lo_inc, "hi_inc": hi_inc,
            "lo_prev": lo_prev, "hi_prev": hi_prev,
            "imb5": fl["fl_imb_5m"].to_numpy(np.float64),
            "imb15": fl["fl_imb_15m"].to_numpy(np.float64),
            "covered": np.isfinite(fl["fl_delta"].to_numpy(np.float64)),
        }
    return prep


def make_build(prep, kind: str):
    def build(data, p):
        masks, stops = {}, {}
        for sd, d in data.items():
            n = len(d.bars)
            pr = prep.get(sd)
            if pr is None:
                masks[sd] = (np.zeros(n, bool), np.zeros(n, bool))
                stops[sd] = np.full(n, np.nan)
                continue
            atr5 = d.f["atr_5m"]
            ok = pr["covered"] & np.isfinite(atr5) & (atr5 > 0)
            if kind == "absorption_fade":
                near_lo = (d.close - pr["lo_inc"]) <= 0.25 * atr5
                near_hi = (pr["hi_inc"] - d.close) <= 0.25 * atr5
                sig_l = ok & near_lo & (pr["imb5"] >= p["imb"])
                sig_s = ok & near_hi & (pr["imb5"] <= -p["imb"])
                stop_l = (d.close - pr["lo_inc"]) + p["stop_s"] * atr5
                stop_s_ = (pr["hi_inc"] - d.close) + p["stop_s"] * atr5
            elif kind == "delta_break_confirm":
                early = d.minute_et < BREAK_CUTOFF_MIN
                sig_l = ok & early & (d.close > pr["hi_prev"]) & (pr["imb5"] >= p["imb"])
                sig_s = ok & early & (d.close < pr["lo_prev"]) & (pr["imb5"] <= -p["imb"])
                stop_l = np.full(n, np.nan)
                stop_l[sig_l] = (p["stop_s"] * atr5)[sig_l]
                stop_s_ = np.full(n, np.nan)
                stop_s_[sig_s] = (p["stop_s"] * atr5)[sig_s]
            else:  # divergence_reversal
                new_hi = d.close > pr["hi_prev"]
                new_lo = d.close < pr["lo_prev"]
                sig_l = ok & new_lo & (pr["imb15"] >= p["imb"])
                sig_s = ok & new_hi & (pr["imb15"] <= -p["imb"])
                stop_l = (d.close - np.minimum(pr["lo_inc"], d.close)) + p["stop_s"] * atr5
                stop_s_ = (np.maximum(pr["hi_inc"], d.close) - d.close) + p["stop_s"] * atr5
            st = np.where(sig_l, stop_l, np.where(sig_s, stop_s_, np.nan))
            masks[sd] = (sig_l, sig_s)
            stops[sd] = common.clamp_stops(st)
        return masks, stops, p["target_r"], HORIZON, p["window"]
    return build


def run(split: str, run_id: str | None = None):
    from app.research.flow import load_flow

    if split != "train":
        raise ValueError("orderflow cycle-2 evaluation is train-only")
    flow = load_flow(split)
    flow_by_session = dict(tuple(flow.groupby("session")))
    data = {sd: d for sd, d in
            common.load_split(split, COLUMNS, run_id).items()
            if sd in flow_by_session}
    print(f"  flow-covered sessions: {len(data)}")

    results = []
    for kind, axes in SUBGRIDS.items():
        rows = common.evaluate_grid(data, axes, make_build(_prep(data, flow_by_session), kind),
                                    verbose=False)
        for p, m, g in rows:
            results.append(({"kind": kind, **p}, m, g))
    return results


def report(results) -> str:
    lines = []
    passed = [r for r in results if r[2].get("train_pass")]
    lines.append(f"train-gate passers: {len(passed)}/{len(results)}")
    import json
    for p, m, g in sorted(results, key=lambda r: -(r[1].get("pf", 0)
                                                   if r[1].get("n", 0) >= 30 else 0))[:8]:
        lines.append(f"  {json.dumps(p)}")
        lines.append(f"       n={m.get('n')} pf={m.get('pf', 0):.2f} "
                     f"exp=${m.get('expectancy_usd', 0):.2f} "
                     f"t={m.get('bootstrap_t', 0):.1f} "
                     f"{'PASS' if g.get('train_pass') else 'fail(' + ','.join(g.get('failed', [])) + ')'}")
    return "\n".join(lines)
