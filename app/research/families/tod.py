"""Time-of-day study (research/specs/tod.md): descriptive expectancy of the
canonical brackets by 30-min bucket x direction (x regime when frozen).

No selection happens here — output is a table; <=3 candidate windows per
family get appended to family specs before those families register.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FAMILY = "tod"
SPEC_ID = "tod-v1"
HYPOTHESIS = ("Net-of-cost canonical-bracket expectancy is not uniform across "
              "the session; most 30-min buckets are unprofitable both ways and "
              "any edge concentrates in few buckets. If no bucket x direction "
              "cell reaches |bootstrap-t| >= 2, families run full-RTH windows.")

PARAMS_GRID = {
    "bucket_minutes": 30,
    "arms": ["fwd_long_1r_60m", "fwd_short_1r_60m",
             "fwd_long_2r_60m", "fwd_short_2r_60m"],
}


def _boot_t(vals: np.ndarray, iters: int = 10_000, seed: int = 7) -> float:
    """Bootstrap t of the mean over per-session values."""
    if len(vals) < 8:
        return 0.0
    rng = np.random.default_rng(seed)
    means = rng.choice(vals, size=(iters, len(vals)), replace=True).mean(axis=1)
    se = means.std()
    return float(vals.mean() / se) if se > 0 else 0.0


def run(split: str, run_id: str) -> list[tuple[dict, dict, dict]]:
    from app.research.features import load_features
    from app.research.outcomes import load_outcomes

    if split != "train":
        raise ValueError("the tod study is train-only by design")
    feats = load_features(split)
    oc = load_outcomes(split)
    if len(feats) != len(oc):
        raise RuntimeError("features/outcomes row mismatch")

    bucket = (feats["minute_of_rth"].to_numpy()
              // PARAMS_GRID["bucket_minutes"]).astype(int)
    rth = feats["is_rth"].to_numpy() > 0
    sess = feats["session"].to_numpy()

    results = []
    for arm in PARAMS_GRID["arms"]:
        y = oc[arm].to_numpy()
        for b in range(13):                      # 09:30..16:00 in 30m buckets
            sel = rth & (bucket == b) & np.isfinite(y)
            if sel.sum() < 500:
                continue
            per_sess = pd.Series(y[sel]).groupby(sess[sel]).mean()
            vals = per_sess.to_numpy()
            h = 9 * 60 + 30 + b * 30
            metrics = {
                "bucket_et": f"{h // 60:02d}:{h % 60:02d}",
                "n_bars": int(sel.sum()),
                "n_sessions": int(len(vals)),
                "mean_r": round(float(y[sel].mean()), 4),
                "boot_t": round(_boot_t(vals), 2),
            }
            results.append(({"arm": arm, "bucket": b}, metrics, {}))
    return results


def report(results) -> str:
    """Human-readable grid: rows = buckets, cols = arms (mean R / t)."""
    arms = PARAMS_GRID["arms"]
    by_key = {(p["arm"], p["bucket"]): m for p, m, _ in results}
    buckets = sorted({p["bucket"] for p, _, _ in results})
    lines = ["bucket  " + "  ".join(f"{a.replace('fwd_', ''):>16s}" for a in arms)]
    for b in buckets:
        t0 = 9 * 60 + 30 + b * 30
        cells = []
        for a in arms:
            m = by_key.get((a, b))
            cells.append(f"{m['mean_r']:+.3f} (t{m['boot_t']:+.1f})".rjust(16)
                         if m else " " * 16)
        lines.append(f"{t0 // 60:02d}:{t0 % 60:02d}   " + "  ".join(cells))
    return "\n".join(lines)
