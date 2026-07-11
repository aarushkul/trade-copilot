"""Expanding walk-forward CV by quarter over train (research/specs/ml.md).

Sessions never straddle folds; labels resolve inside their own session
(force-flat), so session-level splitting inherently satisfies the purge;
the embargo drops the last session of each training window anyway.
"""
from __future__ import annotations

import numpy as np

EMBARGO_SESSIONS = 1
MIN_TRAIN_QUARTERS = 2


def quarter_of(session: str) -> str:
    y, m = session[:4], int(session[5:7])
    return f"{y}Q{(m - 1) // 3 + 1}"


def folds(sessions: np.ndarray) -> list[tuple[np.ndarray, np.ndarray, str]]:
    """[(train_row_mask, test_row_mask, test_quarter)] over row-aligned
    session labels. Expanding: fold k trains on quarters < q_k."""
    qs = np.array([quarter_of(s) for s in sessions])
    uniq = sorted(set(qs))
    out = []
    for k in range(MIN_TRAIN_QUARTERS, len(uniq)):
        q = uniq[k]
        train_m = np.isin(qs, uniq[:k])
        # embargo: drop the last EMBARGO_SESSIONS sessions before the fold
        train_sessions = sorted(set(sessions[train_m]))
        for s in train_sessions[-EMBARGO_SESSIONS:]:
            train_m &= sessions != s
        test_m = qs == q
        if train_m.sum() and test_m.sum():
            out.append((train_m, test_m, q))
    return out
