"""Build the research feature store, then verify causality on real data.

Usage:
    .venv/bin/python scripts/research/build_features.py [--skip-verify]

The post-build verification replays the corpus walk and, for a sample of
sessions, rebuilds features from truncated bars with a deep-copied state
snapshot — cached rows must be bit-identical (the anti-lookahead gate from
research/README.md, on the real tape).
"""
from __future__ import annotations

import argparse
import copy
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.indicators.noise import NoiseBands  # noqa: E402
from app.research import data as datamod  # noqa: E402
from app.research import splits  # noqa: E402
from app.research.features import (  # noqa: E402
    build_all, build_session, load_features, session_rth_summary)


def verify(n_sessions: int = 10, seed: int = 5) -> None:
    from collections import deque
    from statistics import median

    all_sessions = datamod.sessions(include_roll=True)
    meta = datamod.session_meta()
    train = load_features("train")
    rng = np.random.default_rng(seed)
    train_sds = sorted(set(train["session"]))
    sample = set(rng.choice(train_sds, size=n_sessions, replace=False))

    noise = NoiseBands()
    prev_rth = None
    or15_hist: deque[float] = deque(maxlen=14)
    checked = 0
    for sd in sorted(all_sessions):
        bars = all_sessions[sd]
        or15_med = median(or15_hist) if or15_hist else None
        if sd in sample and not meta[sd].is_roll:
            t = int(rng.integers(60, len(bars) - 1))
            trunc = build_session(bars[: t + 1], copy.deepcopy(noise),
                                  prev_rth, or15_med)
            cached = train[train["session"] == sd].reset_index(drop=True)
            np.testing.assert_array_equal(
                cached.iloc[t, 1:].to_numpy(dtype=np.float32),
                trunc.iloc[t].to_numpy(dtype=np.float32),
                err_msg=f"LOOKAHEAD at {sd} bar {t}")
            checked += 1
        # feed state exactly as the builder did
        for b in bars:
            noise.on_minute_bar(b)
        summ = session_rth_summary(bars)
        if summ:
            prev_rth = summ
            if summ.get("or15_width"):
                or15_hist.append(summ["or15_width"])
    print(f"anti-lookahead verify: {checked} real (session, t) probes passed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    counts = build_all()
    print(f"build: {sum(counts.values()):,} rows in {time.time() - t0:.0f}s")
    if not args.skip_verify:
        verify()
    t1 = time.time()
    from app.research import outcomes
    outcomes.build_all()
    print(f"outcomes: done in {time.time() - t1:.0f}s")


if __name__ == "__main__":
    main()
