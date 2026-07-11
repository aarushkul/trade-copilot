"""Gate metrics for research results (thresholds in research/README.md)."""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from app.research.sim import Trade


def gate_metrics(trades: list[Trade], seed: int = 7) -> dict:
    """Everything the train gate needs, from one variant's trade list."""
    if not trades:
        return {"n": 0}
    pnls = np.array([t.pnl_usd for t in trades])
    rs = np.array([t.r for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    gross_loss = -losses.sum()

    by_month: dict[str, float] = defaultdict(float)
    by_session: dict[str, float] = defaultdict(float)
    for t in trades:
        by_month[t.session[:7]] += t.pnl_usd
        by_session[t.session] += t.pnl_usd
    months = list(by_month.values())

    top_k = max(1, len(pnls) // 10)
    top_share = (np.sort(pnls)[::-1][:top_k].sum() / pnls.sum()) if pnls.sum() > 0 else math.inf

    half = len(pnls) // 2
    def _pf(x):
        gl = -x[x <= 0].sum()
        return float(x[x > 0].sum() / gl) if gl > 0 else math.inf

    # equity max drawdown over the trade sequence
    eq = np.cumsum(pnls)
    max_dd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) else 0.0

    return {
        "n": int(len(pnls)),
        "pf": _pf(pnls),
        "expectancy_usd": float(pnls.mean()),
        "expectancy_r": float(rs.mean()),
        "win_rate": float(len(wins) / len(pnls) * 100),  # diagnostics only, never selected on
        "pnl": float(pnls.sum()),
        "max_dd": max_dd,
        "months_pos_frac": float(sum(1 for m in months if m > 0) / len(months)),
        "n_months": len(months),
        "top10_share": float(top_share),
        "bootstrap_t": bootstrap_t(by_session, seed=seed),
        "h1_pf": _pf(pnls[:half]) if half else math.nan,
        "h2_pf": _pf(pnls[half:]) if half else math.nan,
    }


def bootstrap_t(pnl_by_session: dict[str, float], iters: int = 10_000,
                seed: int = 7) -> float:
    """Session-block bootstrap t-stat of mean session P&L.

    Resampling whole sessions respects intraday correlation between trades.
    """
    vals = np.array(list(pnl_by_session.values()))
    if len(vals) < 8:
        return 0.0
    rng = np.random.default_rng(seed)
    means = rng.choice(vals, size=(iters, len(vals)), replace=True).mean(axis=1)
    se = means.std()
    return float(vals.mean() / se) if se > 0 else 0.0


def train_gates(metrics: dict, stress_pf: float | None = None) -> dict:
    """Apply the pre-registered train-advance gate. Returns pass/fail detail.
    The plateau rule is grid-level and applied by the runner, not here."""
    failed = []
    if metrics.get("n", 0) < 150:
        failed.append("n>=150")
    if metrics.get("pf", 0) < 1.25:
        failed.append("pf>=1.25")
    if metrics.get("months_pos_frac", 0) < 0.60:
        failed.append("months_pos>=60%")
    if metrics.get("top10_share", math.inf) >= 0.40:
        failed.append("top10_share<40%")
    if metrics.get("bootstrap_t", 0) < 2.0:
        failed.append("bootstrap_t>=2")
    if stress_pf is not None and stress_pf <= 1.0:
        failed.append("stress_1.5x_slip_pf>1.0")
    return {"train_pass": not failed, "failed": failed}
