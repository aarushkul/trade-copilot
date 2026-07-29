"""Shared harness for trade-rule families.

A family defines AXES (ordered grid values), builds (long, short, stop_pts)
per session for one grid point, and this module does the rest: sim-1 run,
gate metrics, 1.5x-slippage stress, plateau rule, survivor selection.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np

from app.research import sim, stats

ET = ZoneInfo("America/New_York")

WINDOWS = {                       # ET-minute signal windows (inclusive)
    "rth": (570, 945),            # 09:30..15:45 (run_rule default)
    "w1": (660, 840),             # 11:00..14:00 (tod-window-1)
    "w2": (630, 900),             # 10:30..15:00 (tod-window-2)
}

STOP_CLAMP = (5.0, 45.0)          # engine's live stop clamp, points


@dataclass
class SessionData:
    """Bars + aligned numpy feature columns for one session."""
    bars: list
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    minute_et: np.ndarray
    f: dict[str, np.ndarray]      # feature columns, aligned to bars


def load_split(split: str, columns: list[str],
               run_id: str | None = None) -> dict[str, SessionData]:
    """One-time load: bars + the feature columns a family needs."""
    from app.research import data as datamod
    from app.research.features import load_features

    feats = load_features(split, run_id)
    all_sessions = datamod.sessions(include_roll=False)
    out: dict[str, SessionData] = {}
    for sd, g in feats.groupby("session", sort=True):
        bars = all_sessions[sd]
        if len(g) != len(bars):
            raise RuntimeError(f"{sd}: feature/bar row mismatch")
        out[sd] = SessionData(
            bars=bars,
            open=np.array([b.open for b in bars]),
            high=np.array([b.high for b in bars]),
            low=np.array([b.low for b in bars]),
            close=np.array([b.close for b in bars]),
            minute_et=g["minute_et"].to_numpy(np.float64),
            f={c: g[c].to_numpy(np.float64) for c in columns},
        )
    return out


def rolling_min(a: np.ndarray, w: int) -> np.ndarray:
    """Trailing min over the last w bars including current (causal)."""
    import pandas as pd
    return pd.Series(a).rolling(w, min_periods=1).min().to_numpy()


def rolling_max(a: np.ndarray, w: int) -> np.ndarray:
    import pandas as pd
    return pd.Series(a).rolling(w, min_periods=1).max().to_numpy()


def clamp_stops(stop_pts: np.ndarray) -> np.ndarray:
    """Live-engine stop clamp: too-wide stops kill the signal (NaN), too
    narrow get floored."""
    s = stop_pts.copy()
    s[s > STOP_CLAMP[1]] = np.nan
    lo = STOP_CLAMP[0]
    s[(s > 0) & (s < lo)] = lo
    return s


def grid_points(axes: dict[str, list]) -> list[dict]:
    names = list(axes)
    return [dict(zip(names, combo))
            for combo in itertools.product(*(axes[n] for n in names))]


def _neighbors(p: dict, axes: dict[str, list]) -> list[dict]:
    """Grid points differing by exactly one step on exactly one axis."""
    out = []
    for name, values in axes.items():
        i = values.index(p[name])
        for j in (i - 1, i + 1):
            if 0 <= j < len(values):
                q = dict(p)
                q[name] = values[j]
                out.append(q)
    return out


def _key(p: dict) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in p.items()))


def evaluate_grid(data: dict[str, SessionData], axes: dict[str, list],
                  build, verbose: bool = True) -> list[tuple[dict, dict, dict]]:
    """build(data, params) -> (masks, stops, target_r, horizon, window_key).

    Returns [(params, metrics, gates)] with plateau applied grid-wide and
    survivors flagged (pass all train gates + stress + plateau).
    """
    points = grid_points(axes)
    rows = []
    pf_by_key: dict[tuple, float] = {}
    for n, p in enumerate(points):
        masks, stops, target_r, horizon, window_key = build(data, p)
        sessions_bars = {sd: d.bars for sd, d in data.items()}
        window = WINDOWS[window_key]
        trades = sim.run_rule(sessions_bars, masks, stops, target_r=target_r,
                              horizon_min=horizon, window=window)
        m = stats.gate_metrics(trades)
        stress_pf = None
        if m.get("n", 0) >= 150 and m.get("pf", 0) >= 1.25:
            stress = sim.run_rule(sessions_bars, masks, stops,
                                  target_r=target_r, horizon_min=horizon,
                                  window=window, slippage_ticks=1.5)
            sm = stats.gate_metrics(stress)
            stress_pf = sm.get("pf")
            m["stress_pf"] = round(stress_pf, 3) if stress_pf is not None else None
        g = stats.train_gates(m, stress_pf=stress_pf)
        pf_by_key[_key(p)] = m.get("pf", 0.0)
        rows.append((p, m, g))
        if verbose and (n + 1) % 50 == 0:
            print(f"  {n + 1}/{len(points)} grid points done")

    # plateau rule (grid-level): median PF of +/-1 neighbors >= 1.15
    for p, m, g in rows:
        if not g["train_pass"]:
            continue
        neigh = [pf_by_key[_key(q)] for q in _neighbors(p, axes)
                 if _key(q) in pf_by_key]
        med = median(neigh) if neigh else 0.0
        m["plateau_median_pf"] = round(med, 3)
        if med < 1.15:
            g["train_pass"] = False
            g["failed"] = g.get("failed", []) + ["plateau_median_pf>=1.15"]
    return rows


def evaluate_grid_trail(data: dict[str, SessionData], axes: dict[str, list],
                        build, verbose: bool = True
                        ) -> list[tuple[dict, dict, dict]]:
    """evaluate_grid for stop-only trailing exits (sim-1.1).

    build(data, params) -> (masks, stops, trails, window_key). Same gates,
    stress pass, and plateau rule as the bracket path.
    """
    points = grid_points(axes)
    rows = []
    pf_by_key: dict[tuple, float] = {}
    sessions_bars = {sd: d.bars for sd, d in data.items()}
    arrays = {sd: (d.open, d.high, d.low, d.close,
                   np.array([b.ts for b in d.bars]), d.minute_et)
              for sd, d in data.items()}
    for n, p in enumerate(points):
        masks, stops, trails, window_key = build(data, p)
        window = WINDOWS[window_key]
        trades = sim.run_rule_trail(sessions_bars, masks, stops, trails,
                                    window=window, arrays=arrays)
        m = stats.gate_metrics(trades)
        stress_pf = None
        if m.get("n", 0) >= 150 and m.get("pf", 0) >= 1.25:
            stress = sim.run_rule_trail(sessions_bars, masks, stops, trails,
                                        window=window, slippage_ticks=1.5,
                                        arrays=arrays)
            sm = stats.gate_metrics(stress)
            stress_pf = sm.get("pf")
            m["stress_pf"] = round(stress_pf, 3) if stress_pf is not None else None
        g = stats.train_gates(m, stress_pf=stress_pf)
        pf_by_key[_key(p)] = m.get("pf", 0.0)
        rows.append((p, m, g))
        if verbose and (n + 1) % 50 == 0:
            print(f"  {n + 1}/{len(points)} grid points done")

    for p, m, g in rows:
        if not g["train_pass"]:
            continue
        neigh = [pf_by_key[_key(q)] for q in _neighbors(p, axes)
                 if _key(q) in pf_by_key]
        med = median(neigh) if neigh else 0.0
        m["plateau_median_pf"] = round(med, 3)
        if med < 1.15:
            g["train_pass"] = False
            g["failed"] = g.get("failed", []) + ["plateau_median_pf>=1.15"]
    return rows


def survivors(rows: list[tuple[dict, dict, dict]], axes: dict[str, list],
              max_n: int = 2) -> list[dict]:
    """<= max_n non-adjacent passers, best expectancy first."""
    passed = sorted((r for r in rows if r[2]["train_pass"]),
                    key=lambda r: -r[1].get("expectancy_usd", 0))
    chosen: list[dict] = []
    for p, _, _ in passed:
        if len(chosen) >= max_n:
            break
        if all(_key(p) not in {_key(q) for q in _neighbors(c, axes)}
               and _key(p) != _key(c) for c in chosen):
            chosen.append(p)
    return chosen


def et_minute(ts: float) -> int:
    dt = datetime.fromtimestamp(ts, tz=ET)
    return dt.hour * 60 + dt.minute
