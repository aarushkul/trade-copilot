"""Build the flow feature store, then run the pre-registered proxy checks.

Checks (research/specs/orderflow.md addendum):
  1. proxy credibility: corr(proxy minute delta, TRUE trades minute delta)
     over the validation month must be >= 0.8
  2. side-convention decode: corr(true delta, same-minute MNQ return) > 0
  3. proxy sanity: corr(proxy delta, MNQ return) > 0 in every quarter of 2025

Usage: .venv/bin/python scripts/research/build_flow.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import HISTORY_DIR  # noqa: E402
from app.research import data as datamod  # noqa: E402
from app.research.flow import build_all  # noqa: E402


def mnq_minute_returns() -> pd.DataFrame:
    rows = []
    for sd, bars in datamod.sessions(include_roll=False).items():
        if not ("2025-01-01" <= sd <= "2025-12-10"):
            continue
        for b in bars:
            rows.append((b.ts, b.close - b.open))
    df = pd.DataFrame(rows, columns=["ts", "ret"])
    return df.drop_duplicates("ts")


def verify() -> None:
    proxy = pd.read_parquet(HISTORY_DIR / "flow_NQ1s_2025.parquet")
    true = pd.read_parquet(HISTORY_DIR / "flow_NQtrades_val.parquet")
    proxy["p_delta"] = proxy["buy_vol"] - proxy["sell_vol"]
    true["t_delta"] = true["buy_vol"] - true["sell_vol"]

    j = proxy.merge(true[["ts", "t_delta"]], on="ts", how="inner")
    c1 = float(np.corrcoef(j["p_delta"], j["t_delta"])[0, 1])
    print(f"proxy vs true delta (n={len(j):,} overlap minutes): corr={c1:.3f} "
          f"{'PASS (>=0.8)' if c1 >= 0.8 else 'FAIL — proxy too weak'}")

    ret = mnq_minute_returns()
    jt = true.merge(ret, on="ts", how="inner")
    c2 = float(np.corrcoef(jt["t_delta"], jt["ret"])[0, 1])
    print(f"true delta vs MNQ 1m return (n={len(jt):,}): corr={c2:.3f} "
          f"{'PASS (side decode correct)' if c2 > 0 else 'FAIL — side inverted'}")

    jp = proxy.merge(ret, on="ts", how="inner")
    jp["q"] = pd.to_datetime(jp["ts"], unit="s", utc=True).dt.quarter
    print("proxy delta vs MNQ return by quarter:")
    for q, g in jp.groupby("q"):
        cq = float(np.corrcoef(g["p_delta"], g["ret"])[0, 1])
        print(f"  Q{q}: corr={cq:.3f} n={len(g):,} "
              f"{'ok' if cq > 0 else 'NEGATIVE'}")


def main() -> None:
    t0 = time.time()
    counts = build_all()
    print(f"flow store: {counts} in {time.time() - t0:.0f}s")
    verify()


if __name__ == "__main__":
    main()
