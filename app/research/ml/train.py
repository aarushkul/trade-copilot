"""ML track (research/specs/ml.md): logistic baseline + HistGradientBoosting,
expanding walk-forward CV, theta-policy evaluated through sim-1 fills and the
standard train gates.

Theta is causal: for each fold it is the q-quantile of the model's
predictions on ITS OWN training window — no pooled-future calibration.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.research.families import common
from app.research.ml import cv, dataset

FAMILY = "ml"
SPEC_ID = "ml-v1"
HYPOTHESIS = ("A regularized tabular model over the causal features predicts "
              "net-of-cost forward bracket R well enough that 'enter when "
              "prediction > theta' passes the same train gates as the rule "
              "families; otherwise learned patterns add nothing at this "
              "data scale.")

AXES = {
    "model": ["logistic", "hgb"],
    "side": ["long", "short"],
    "y_arm_target": [1.0, 2.0],          # fwd_{side}_{1,2}r_60m, horizon 60
    "theta_q": [0.55, 0.60, 0.65, 0.70],
}
PARAMS_GRID = {**AXES, "cv": "expanding-quarterly, embargo 1 session",
               "theta": "quantile of fold-train predictions (causal)",
               "stop": "1.0 x atr_5m (canonical, 5-45pt live clamp)"}

HORIZON_MIN = 60


def _fit(model_name: str, X, y, seed: int = 7):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if model_name == "logistic":
        clf = make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(),
            LogisticRegression(C=0.1, max_iter=2000, random_state=seed))
    else:
        clf = HistGradientBoostingClassifier(
            max_depth=4, learning_rate=0.05, max_iter=300,
            min_samples_leaf=200, l2_regularization=1.0,
            validation_fraction=0.15, early_stopping=True,
            random_state=seed)
    clf.fit(X, y)
    return clf


def oos_predictions(feats: pd.DataFrame, oc: pd.DataFrame, model_name: str,
                    y_arm: str, verbose: bool = True):
    """Pooled out-of-fold P(win) plus each fold's train-quantile thresholds.

    Returns (row_idx_into_feats, oos_pred, theta_by_q[fold_rows]) where
    theta arrays align with row_idx."""
    X, y, sess, idx = dataset.build_xy(feats, oc, y_arm)
    Xv = X.to_numpy(np.float32)
    pred = np.full(len(y), np.nan)
    thetas = {q: np.full(len(y), np.nan) for q in AXES["theta_q"]}
    for train_m, test_m, quarter in cv.folds(sess):
        clf = _fit(model_name, Xv[train_m], y[train_m])
        p_tr = clf.predict_proba(Xv[train_m])[:, 1]
        p_te = clf.predict_proba(Xv[test_m])[:, 1]
        pred[test_m] = p_te
        for q in AXES["theta_q"]:
            thetas[q][test_m] = np.quantile(p_tr, q)
        if verbose:
            print(f"    fold {quarter}: train n={train_m.sum():,} "
                  f"test n={test_m.sum():,} mean_p={p_te.mean():.3f}")
    return idx, sess, pred, thetas


def run(split: str, run_id: str | None = None):
    from app.research.features import load_features
    from app.research.outcomes import load_outcomes

    feats = load_features(split, run_id)
    oc = load_outcomes(split, run_id)
    data = common.load_split(split, ["atr_5m"], run_id)

    n_rows = len(feats)
    results = []
    for model_name in AXES["model"]:
        for side in AXES["side"]:
            for tr in AXES["y_arm_target"]:
                y_arm = f"fwd_{side}_{int(tr)}r_{HORIZON_MIN}m"
                print(f"  {model_name} {y_arm}")
                idx, sess, pred, thetas = oos_predictions(
                    feats, oc, model_name, y_arm)
                have = np.isfinite(pred)
                for q in AXES["theta_q"]:
                    sig_rows = idx[have & (pred > thetas[q])]
                    p = {"model": model_name, "side": side,
                         "y_arm_target": tr, "theta_q": q}
                    m = _evaluate_policy(data, feats, sig_rows, side, tr,
                                         n_rows)
                    from app.research import stats
                    g = stats.train_gates(m, stress_pf=m.get("stress_pf"))
                    results.append((p, m, g))
    return results


def _evaluate_policy(data, feats, sig_rows: np.ndarray, side: str,
                     target_r: float, n_rows: int) -> dict:
    """Turn signal row indices into per-session masks and run sim-1."""
    from app.research import sim, stats

    sig = np.zeros(n_rows, bool)
    sig[sig_rows] = True
    sessions_col = feats["session"].to_numpy()
    masks, stops = {}, {}
    pos = 0
    for sd, d in data.items():
        n = len(d.bars)
        s = sig[pos: pos + n]
        zero = np.zeros(n, bool)
        masks[sd] = (s, zero) if side == "long" else (zero, s)
        stops[sd] = common.clamp_stops(d.f["atr_5m"].copy())
        if sessions_col[pos] != sd:
            raise RuntimeError("row alignment broken")
        pos += n
    bars = {sd: d.bars for sd, d in data.items()}
    trades = sim.run_rule(bars, masks, stops, target_r=target_r,
                          horizon_min=HORIZON_MIN)
    m = stats.gate_metrics(trades)
    if m.get("n", 0) >= 150 and m.get("pf", 0) >= 1.25:
        stress = sim.run_rule(bars, masks, stops, target_r=target_r,
                              horizon_min=HORIZON_MIN, slippage_ticks=1.5)
        sp = stats.gate_metrics(stress).get("pf")
        m["stress_pf"] = round(sp, 3) if sp is not None else None
    return m
