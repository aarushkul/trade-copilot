"""Regime study (research/specs/regime.md): can causal early-session
detectors split sessions into trend/range classes whose forward
drift-to-close actually differs?

Descriptive/conditioning study — no trades. The freeze gate is
pre-registered: separation bootstrap-t >= 2, coverage >= 20% per class,
sign-stable separation across 2023/2024/2025.
"""
from __future__ import annotations

from collections import deque
from statistics import median

import numpy as np
import pandas as pd

FAMILY = "regime"
SPEC_ID = "regime-v1"
HYPOTHESIS = ("Trend vs range days are detectable early from causal features "
              "and the detected classes differ in forward drift-to-close; "
              "if separation bootstrap-t < 2 the layer is dead and dependent "
              "families run unconditioned.")

PARAMS_GRID = {
    "band_breach": {"k": [3, 5, 10], "m": [30, 60, 90]},
    "open_drive": {"thr": [0.75, 1.0, 1.5], "m": [15, 30, 60]},
    "gap": {"thr": [1.0, 2.0], "m": [15]},
    "cumvol": {"thr": [1.2, 1.5], "m": [30, 60, 90]},
}

MIN_COVERAGE = 0.20
SEP_T_GATE = 2.0


def variants() -> list[dict]:
    out = []
    for det, grid in PARAMS_GRID.items():
        keys = [k for k in grid if k != "m"]
        for m in grid["m"]:
            if keys:
                for v in grid[keys[0]]:
                    out.append({"detector": det, keys[0]: v, "m": m})
            else:
                out.append({"detector": det, "m": m})
    return out


def trend_day_labels(split: str = "train") -> dict[str, bool]:
    """Full-session labels (study targets ONLY, never features):
    |RTH close - open| >= 0.65 x range AND range >= 1.2 x median of the
    PRIOR 14 sessions' ranges. Walks the whole corpus so the trailing
    median has history at the split boundary."""
    from app.research import data as datamod
    from app.research import splits
    from app.research.features import session_rth_summary

    all_sessions = datamod.sessions(include_roll=False)
    hist: deque[float] = deque(maxlen=14)
    labels: dict[str, bool] = {}
    for sd in sorted(all_sessions):
        summ = session_rth_summary(all_sessions[sd])
        if not summ or summ["range"] <= 0:
            continue
        if len(hist) >= 8 and splits.split_of(sd) == split:
            labels[sd] = (abs(summ["close"] - summ["open"]) >= 0.65 * summ["range"]
                          and summ["range"] >= 1.2 * median(hist))
        hist.append(summ["range"])
    return labels


def _session_table(feats: pd.DataFrame) -> pd.DataFrame:
    """One row per session with everything every detector needs."""
    rows = []
    for sd, g in feats.groupby("session", sort=True):
        rth = g[g["is_rth"] > 0]
        if len(rth) < 300:
            continue
        mor = rth["minute_of_rth"].to_numpy()
        close = rth["close"].to_numpy()
        row = {"session": sd, "year": sd[:4], "rth_close": close[-1]}
        for m in (15, 30, 60, 90):
            sel = np.flatnonzero(mor == m)
            if not len(sel):
                row[f"ok_{m}"] = False
                continue
            i = sel[0]
            upto = slice(0, i + 1)
            row[f"ok_{m}"] = True
            row[f"close_{m}"] = close[i]
            row[f"atr5_{m}"] = rth["atr_5m"].to_numpy()[i]
            row[f"drive_band_{m}"] = rth["open_drive_band"].to_numpy()[i]
            row[f"drive_atr_{m}"] = rth["open_drive_atr"].to_numpy()[i]
            row[f"gap_{m}"] = rth["gap_atr"].to_numpy()[i]
            row[f"cumvol_{m}"] = rth["cumvol_vs_14d"].to_numpy()[i]
            mb = rth["mins_beyond_band"].to_numpy()[upto]
            row[f"max_beyond_{m}"] = np.nanmax(mb) if np.isfinite(mb).any() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _boot_diff_t(a: np.ndarray, b: np.ndarray, iters: int = 10_000,
                 seed: int = 7) -> float:
    """Bootstrap t of mean(a) - mean(b), independent session groups."""
    if len(a) < 8 or len(b) < 8:
        return 0.0
    rng = np.random.default_rng(seed)
    da = rng.choice(a, size=(iters, len(a)), replace=True).mean(axis=1)
    db = rng.choice(b, size=(iters, len(b)), replace=True).mean(axis=1)
    diffs = da - db
    sd = diffs.std()
    return float((a.mean() - b.mean()) / sd) if sd > 0 else 0.0


def _classify(tab: pd.DataFrame, p: dict) -> pd.DataFrame:
    m = p["m"]
    t = tab[tab.get(f"ok_{m}", False) == True].copy()  # noqa: E712
    if t.empty:
        return t
    det = p["detector"]
    if det == "band_breach":
        sig = t[f"max_beyond_{m}"] >= p["k"]
    elif det == "open_drive":
        sig = t[f"drive_band_{m}"].abs() >= p["thr"]
    elif det == "gap":
        sig = t[f"gap_{m}"].abs() >= p["thr"]
    elif det == "cumvol":
        sig = t[f"cumvol_{m}"] >= p["thr"]
    else:
        raise ValueError(det)
    t["is_trend"] = sig.fillna(False).to_numpy()
    t["direction"] = np.sign(t[f"drive_atr_{m}"].fillna(0.0))
    a5 = t[f"atr5_{m}"].replace(0, np.nan)
    t["fwd_drift_atr"] = (t["rth_close"] - t[f"close_{m}"]) / a5
    t = t[np.isfinite(t["fwd_drift_atr"])]
    return t


def evaluate_variant(tab: pd.DataFrame, p: dict) -> dict:
    t = _classify(tab, p)
    n = len(t)
    if n < 100:
        return {"n_sessions": n, "freeze_pass": False, "failed": ["n>=100"]}
    trend = t[t["is_trend"]]
    rng_ = t[~t["is_trend"]]
    abs_tr = trend["fwd_drift_atr"].abs().to_numpy()
    abs_rg = rng_["fwd_drift_atr"].abs().to_numpy()
    sep_t = _boot_diff_t(abs_tr, abs_rg)
    # directional check: does the early direction persist on trend days?
    dirs = trend["direction"].to_numpy()
    signed = (trend["fwd_drift_atr"].to_numpy() * dirs)[dirs != 0]

    per_year = {}
    for y, g in t.groupby("year"):
        a = g[g["is_trend"]]["fwd_drift_atr"].abs().to_numpy()
        b = g[~g["is_trend"]]["fwd_drift_atr"].abs().to_numpy()
        per_year[y] = round(float(a.mean() - b.mean()), 3) if len(a) >= 5 and len(b) >= 5 else None

    cov_tr = len(trend) / n
    cov_rg = len(rng_) / n
    seps = [v for v in per_year.values() if v is not None]
    failed = []
    if sep_t < SEP_T_GATE:
        failed.append("sep_t>=2")
    if cov_tr < MIN_COVERAGE or cov_rg < MIN_COVERAGE:
        failed.append("coverage>=20%")
    if len(seps) < 3 or any(s <= 0 for s in seps):
        failed.append("sign_stable_2023_2024_2025")

    return {
        "n_sessions": n,
        "coverage_trend": round(cov_tr, 3),
        "coverage_range": round(cov_rg, 3),
        "abs_drift_trend": round(float(abs_tr.mean()), 3) if len(abs_tr) else None,
        "abs_drift_range": round(float(abs_rg.mean()), 3) if len(abs_rg) else None,
        "sep_t": round(sep_t, 2),
        "signed_drift_trend": round(float(signed.mean()), 3) if len(signed) else None,
        "sep_by_year": per_year,
        "freeze_pass": not failed,
        "failed": failed,
    }


def run(split: str, run_id: str) -> list[tuple[dict, dict, dict]]:
    from app.research.features import load_features

    if split != "train":
        raise ValueError("the regime study is train-only by design")
    feats = load_features(split)
    tab = _session_table(feats)
    labels = trend_day_labels(split)
    tab["label_trend"] = tab["session"].map(labels)

    results = []
    for p in variants():
        m = evaluate_variant(tab, p)
        # label agreement, diagnostics only
        t = _classify(tab, p)
        lab = t.dropna(subset=["label_trend"])
        if len(lab):
            det = lab["is_trend"].to_numpy(bool)
            y = lab["label_trend"].to_numpy(bool)
            tp = (det & y).sum()
            m["label_precision"] = round(float(tp / det.sum()), 3) if det.sum() else None
            m["label_recall"] = round(float(tp / y.sum()), 3) if y.sum() else None
            m["label_base_rate"] = round(float(y.mean()), 3)
        gates = {"freeze_pass": m.pop("freeze_pass"), "failed": m.pop("failed")}
        results.append((p, m, gates))
    return results
