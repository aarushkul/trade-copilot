"""ML track plumbing: causal CV folds and dataset firewall."""
import numpy as np
import pytest

from app.research.ml import cv, dataset


def test_quarter_of():
    assert cv.quarter_of("2024-03-05") == "2024Q1"
    assert cv.quarter_of("2024-12-31") == "2024Q4"


def test_folds_are_expanding_and_disjoint():
    sessions = np.array(
        [f"2023-{m:02d}-{d:02d}" for m in range(1, 13) for d in (5, 15, 25)]
        + [f"2024-{m:02d}-{d:02d}" for m in range(1, 7) for d in (5, 15, 25)])
    fs = cv.folds(sessions)
    assert len(fs) == 4      # test quarters 2023Q3..2024Q2; first two train-only
    prev_train = 0
    for train_m, test_m, q in fs:
        assert not (train_m & test_m).any()
        tr_q = {cv.quarter_of(s) for s in sessions[train_m]}
        te_q = {cv.quarter_of(s) for s in sessions[test_m]}
        assert max(tr_q) < min(te_q)         # strictly past-only training
        assert train_m.sum() >= prev_train    # expanding
        prev_train = train_m.sum()
        # embargo: the session immediately before the fold is dropped
        last_before = max(s for s in sessions if s < min(sessions[test_m]))
        assert last_before not in set(sessions[train_m])


def test_dataset_firewall_rejects_fwd_columns():
    import pandas as pd
    df = pd.DataFrame({"session": ["a"], "ts": [1.0], "rsi_1m": [50.0],
                       "fwd_long_1r_60m": [0.1]})
    with pytest.raises(ValueError):
        dataset.feature_columns(df)
