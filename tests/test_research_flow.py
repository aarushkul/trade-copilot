"""Flow layer: tick-rule aggregation golden values + causality + registry."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))

from app.models import Bar
from app.research import families
from app.research.flow import FLOW_COLUMNS, build_session_flow

ET = ZoneInfo("America/New_York")


def test_agg_1s_tick_rule_golden():
    from pull_orderflow import agg_1s

    t0 = pd.Timestamp("2025-03-04 15:30:00", tz="UTC")
    idx = pd.DatetimeIndex([t0, t0 + pd.Timedelta(seconds=1),
                            t0 + pd.Timedelta(seconds=2),
                            t0 + pd.Timedelta(seconds=61)])
    df = pd.DataFrame({
        "open":  [100.0, 101.0, 101.0, 101.0],
        "close": [101.0, 100.0, 101.0, 101.0],   # up, down, doji(up vs prev), doji(flat vs prev)
        "volume": [10, 20, 30, 40],
    }, index=idx)
    out = agg_1s(df).set_index("ts")
    m0 = int(t0.timestamp())
    assert out.at[m0, "buy_vol"] == 10 + 30      # doji resolves UP vs prev close 100->101
    assert out.at[m0, "sell_vol"] == 20
    assert out.at[m0, "n_secs"] == 3
    m1 = m0 + 60
    assert out.at[m1, "buy_vol"] == 20           # flat vs prev -> 50/50 split
    assert out.at[m1, "sell_vol"] == 20


def synthetic(n=120):
    start = datetime(2025, 3, 4, 9, 30, tzinfo=ET)
    rng = np.random.default_rng(4)
    px = 20000.0
    bars, rows = [], []
    for i in range(n):
        ts = (start + timedelta(minutes=i)).timestamp()
        c = px + float(rng.normal(0, 3))
        bars.append(Bar(ts, px, max(px, c) + 1, min(px, c) - 1, c, 100))
        rows.append((ts, float(rng.integers(50, 300)),
                     float(rng.integers(50, 300)), int(rng.integers(20, 60))))
        px = c
    flow = pd.DataFrame(rows, columns=["ts", "buy_vol", "sell_vol", "n_secs"])
    atr5 = np.full(n, 8.0)
    return bars, flow, atr5


def test_flow_columns_are_causal_under_truncation():
    bars, flow, atr5 = synthetic()
    full = build_session_flow(bars, flow, atr5, None)
    assert list(full.columns) == FLOW_COLUMNS
    for t in (40, 77, 119):
        trunc = build_session_flow(bars[: t + 1], flow.iloc[: t + 1], atr5[: t + 1], None)
        np.testing.assert_array_equal(
            full.iloc[t].to_numpy(), trunc.iloc[t].to_numpy(),
            err_msg=f"flow lookahead at bar {t}")


def test_registry_resolves_flow_families():
    assert families.get("orderflow").FAMILY == "orderflow"
    assert families.get("ml_flow").SPEC_ID == "ml-v2-flow"
