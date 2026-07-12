"""ml-v2-flow (research/specs/orderflow.md addendum): the ml harness with
flow columns appended, monthly expanding folds, restricted to flow-covered
sessions. Same models, same causal theta, same sim-1, same gates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.research.families import common
from app.research.ml import cv, dataset
from app.research.ml.train import AXES as ML_AXES
from app.research.ml.train import HORIZON_MIN, _evaluate_policy, _fit

FAMILY = "ml"
SPEC_ID = "ml-v2-flow"
HYPOTHESIS = ("Adding NQ aggressor-flow proxy features to the causal set "
              "lets a tabular model pass the train gates where ml-v1 "
              "(PF 0.98) could not; otherwise flow adds no learnable edge "
              "at this timescale (scoped: 1s tick-rule proxy, 2025).")

AXES = ML_AXES
PARAMS_GRID = {**AXES, "features": "v1 + flow(v1)",
               "folds": "expanding monthly, min 3 train months, embargo 1 session",
               "coverage": "flow-covered sessions only"}


def run(split: str, run_id: str | None = None):
    from app.research import stats
    from app.research.features import load_features
    from app.research.flow import FLOW_COLUMNS, load_flow
    from app.research.outcomes import load_outcomes

    if split != "train":
        raise ValueError("ml-v2-flow is train-only in cycle 2")
    feats = load_features(split)
    oc = load_outcomes(split)
    fl = load_flow(split)

    covered = set(fl["session"])
    keep = feats["session"].isin(covered).to_numpy()
    # positional row alignment within covered sessions (same builder walk)
    feats_c = feats[keep].reset_index(drop=True)
    oc_c = oc[keep].reset_index(drop=True)
    if not (feats_c["ts"].to_numpy() == fl["ts"].to_numpy()).all():
        raise RuntimeError("flow/features ts misalignment")
    merged = pd.concat([feats_c, fl[FLOW_COLUMNS].reset_index(drop=True)], axis=1)

    data = {sd: d for sd, d in
            common.load_split(split, ["atr_5m"], run_id).items()
            if sd in covered}
    n_rows = len(merged)

    results = []
    for model_name in AXES["model"]:
        for side in AXES["side"]:
            for tr in AXES["y_arm_target"]:
                y_arm = f"fwd_{side}_{int(tr)}r_{HORIZON_MIN}m"
                print(f"  {model_name} {y_arm} (+flow)")
                X, y, sess, idx = dataset.build_xy(merged, oc_c, y_arm)
                Xv = X.to_numpy(np.float32)
                pred = np.full(len(y), np.nan)
                thetas = {q: np.full(len(y), np.nan) for q in AXES["theta_q"]}
                for train_m, test_m, month in cv.folds_monthly(sess):
                    clf = _fit(model_name, Xv[train_m], y[train_m])
                    p_tr = clf.predict_proba(Xv[train_m])[:, 1]
                    pred[test_m] = clf.predict_proba(Xv[test_m])[:, 1]
                    for q in AXES["theta_q"]:
                        thetas[q][test_m] = np.quantile(p_tr, q)
                have = np.isfinite(pred)
                for q in AXES["theta_q"]:
                    sig_rows = idx[have & (pred > thetas[q])]
                    p = {"model": model_name, "side": side,
                         "y_arm_target": tr, "theta_q": q, "features": "v1+flow"}
                    m = _evaluate_policy(data, merged, sig_rows, side, tr, n_rows)
                    g = stats.train_gates(m, stress_pf=m.get("stress_pf"))
                    results.append((p, m, g))
    return results
