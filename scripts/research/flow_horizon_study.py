"""Information-horizon study on the owned true-trades month.

Per the registered decision rule in research/specs/orderflow.md: pooled
corr of true-flow features vs net forward MNQ moves at 1/5/15/30/60 min,
RTH-only, session-block bootstrap CIs. Registers in the ledger before
computing. Descriptive — no trades, no gates, no selection.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import HISTORY_DIR  # noqa: E402
from app.research import data as datamod  # noqa: E402
from app.research import ledger  # noqa: E402

ET = ZoneInfo("America/New_York")
HORIZONS = (1, 5, 15, 30, 60)
PREDICTORS = ("delta_1m", "imb_5m", "imb_15m")
RTH_OPEN, RTH_CLOSE = 9 * 60 + 30, 16 * 60


def _roll(a: np.ndarray, w: int) -> np.ndarray:
    c = np.cumsum(a)
    o = c.copy()
    o[w:] = c[w:] - c[:-w]
    return o


def build_rows() -> pd.DataFrame:
    true = pd.read_parquet(HISTORY_DIR / "flow_NQtrades_val.parquet")
    fr = true.set_index("ts")
    rows = []
    for sd, bars in sorted(datamod.sessions(include_roll=False).items()):
        if not ("2025-11-10" <= sd <= "2025-12-10"):
            continue
        ts = np.array([b.ts for b in bars])
        close = np.array([b.close for b in bars])
        buy = fr["buy_vol"].reindex(ts).to_numpy()
        sell = fr["sell_vol"].reindex(ts).to_numpy()
        if not np.isfinite(buy).any():
            continue
        buy, sell = np.nan_to_num(buy), np.nan_to_num(sell)
        delta = buy - sell
        tot = buy + sell
        d5, t5 = _roll(delta, 5), _roll(tot, 5)
        d15, t15 = _roll(delta, 15), _roll(tot, 15)
        minute = np.array([datetime.fromtimestamp(t, tz=ET).hour * 60
                           + datetime.fromtimestamp(t, tz=ET).minute for t in ts])
        rth = (minute >= RTH_OPEN) & (minute < RTH_CLOSE)
        n = len(bars)
        for i in np.flatnonzero(rth):
            row = {"session": sd,
                   "delta_1m": delta[i],
                   "imb_5m": d5[i] / max(t5[i], 1.0),
                   "imb_15m": d15[i] / max(t15[i], 1.0)}
            ok = False
            for h in HORIZONS:
                j = i + h
                # forward window must stay inside this session's RTH
                if j < n and rth[j] and (ts[j] - ts[i]) == 60 * h:
                    row[f"fwd_{h}m"] = close[j] - close[i]
                    ok = True
                else:
                    row[f"fwd_{h}m"] = np.nan
            if ok:
                rows.append(row)
    return pd.DataFrame(rows)


def block_ci(df: pd.DataFrame, x: str, y: str, iters: int = 10_000,
             seed: int = 7) -> tuple[float, float, float, int]:
    sub = df[np.isfinite(df[x]) & np.isfinite(df[y])]
    n = len(sub)
    if n < 500:
        return np.nan, np.nan, np.nan, n
    point = float(np.corrcoef(sub[x], sub[y])[0, 1])
    sessions = sub["session"].unique()
    groups = {s: g for s, g in sub.groupby("session")}
    rng = np.random.default_rng(seed)
    cs = []
    for _ in range(iters):
        pick = rng.choice(sessions, size=len(sessions), replace=True)
        b = pd.concat([groups[s] for s in pick])
        cs.append(np.corrcoef(b[x], b[y])[0, 1])
    lo, hi = np.percentile(cs, [2.5, 97.5])
    return point, float(lo), float(hi), n


def main() -> None:
    run_id = ledger.register({
        "family": "orderflow", "spec_id": "orderflow-horizon-v1",
        "split": "train",
        "hypothesis": "true NQ flow carries forward information at bracket "
                      "horizons (30-60m); decision rule in spec",
        "params_grid": {"predictors": list(PREDICTORS),
                        "horizons": list(HORIZONS),
                        "window": "2025-11-10..2025-12-10 RTH"},
    })
    print(f"registered {run_id}")
    df = build_rows()
    print(f"{df['session'].nunique()} sessions, {len(df):,} RTH rows\n")
    print(f"{'predictor':>10s} " + "  ".join(f"{h:>18d}m" for h in HORIZONS))
    for x in PREDICTORS:
        cells = []
        for h in HORIZONS:
            p, lo, hi, n = block_ci(df, x, f"fwd_{h}m")
            ledger.append_result(run_id, {"predictor": x, "horizon_min": h},
                                 {"corr": None if np.isnan(p) else round(p, 4),
                                  "ci_lo": None if np.isnan(lo) else round(lo, 4),
                                  "ci_hi": None if np.isnan(hi) else round(hi, 4),
                                  "n": n})
            sig = "*" if np.isfinite(lo) and (lo > 0 or hi < 0) else " "
            cells.append(f"{p:+.3f} [{lo:+.3f},{hi:+.3f}]{sig}")
        print(f"{x:>10s} " + "  ".join(cells))
    print("\n* = 95% session-block CI excludes zero")


if __name__ == "__main__":
    main()
