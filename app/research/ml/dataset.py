"""ML dataset assembly (research/specs/ml.md).

X = causal feature matrix, RTH rows, 5-minute stride (autocorrelation cut).
y = sign of net-of-cost forward bracket R for one (side, arm).
The fwd_* firewall applies: X columns are checked by sim.assert_causal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.research.sim import assert_causal

STRIDE_MIN = 5

# identity / non-predictive columns excluded from X
EXCLUDE = {"session", "ts", "minute_et", "is_rth", "close"}


def feature_columns(df: pd.DataFrame) -> list[str]:
    cols = [c for c in df.columns if c not in EXCLUDE]
    assert_causal(cols)
    return cols


def build_xy(feats: pd.DataFrame, oc: pd.DataFrame, y_arm: str
             ) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    """Returns (X, y_binary, session, row_index_into_feats) for RTH rows on
    the 5-min stride with a defined outcome."""
    if len(feats) != len(oc):
        raise RuntimeError("features/outcomes row mismatch")
    y_raw = oc[y_arm].to_numpy()
    sel = ((feats["is_rth"].to_numpy() > 0)
           & (feats["minute_of_rth"].to_numpy() % STRIDE_MIN == 0)
           & np.isfinite(y_raw))
    idx = np.flatnonzero(sel)
    cols = feature_columns(feats)
    X = feats.iloc[idx][cols]
    y = (y_raw[idx] > 0).astype(np.int8)
    sess = feats["session"].to_numpy()[idx]
    return X, y, sess, idx
