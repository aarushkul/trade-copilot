"""Feature layer: anti-lookahead (causality) and basic sanity."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from app.indicators.noise import NoiseBands
from app.models import Bar
from app.research.features import COLUMNS, build_session

ET = ZoneInfo("America/New_York")


def synthetic_session(seed: int = 11, n: int = 240) -> list[Bar]:
    """Deterministic random-walk session starting 18:00 ET prior evening."""
    rng = np.random.default_rng(seed)
    start = datetime(2024, 3, 4, 18, 0, tzinfo=ET)  # session_date 2024-03-05
    px = 18000.0
    bars = []
    for i in range(n):
        drift = float(rng.normal(0, 4))
        o = px
        c = px + drift
        h = max(o, c) + abs(float(rng.normal(0, 1.5)))
        l = min(o, c) - abs(float(rng.normal(0, 1.5)))
        v = int(rng.integers(50, 500))
        bars.append(Bar((start + timedelta(minutes=i)).timestamp(),
                        round(o, 2), round(h, 2), round(l, 2), round(c, 2), v))
        px = c
    return bars


PREV = {"high": 18120.0, "low": 17890.0, "close": 18010.0, "open": 17950.0,
        "range": 230.0, "or15_width": 40.0}


def test_no_lookahead_random_truncations():
    bars = synthetic_session()
    full = build_session(bars, NoiseBands(), PREV, or15_med=35.0)
    rng = np.random.default_rng(3)
    for t in rng.integers(25, len(bars), size=12):
        trunc = build_session(bars[: int(t) + 1], NoiseBands(), PREV, or15_med=35.0)
        np.testing.assert_array_equal(
            full.iloc[int(t)].to_numpy(), trunc.iloc[int(t)].to_numpy(),
            err_msg=f"lookahead detected at bar {t}")


def test_shape_and_columns():
    bars = synthetic_session()
    df = build_session(bars, NoiseBands(), PREV, or15_med=35.0)
    assert list(df.columns) == COLUMNS
    assert len(df) == len(bars)
    assert df["ts"].is_monotonic_increasing
    assert not df.columns.str.startswith("fwd_").any()


def test_prior_day_levels_are_static_references():
    bars = synthetic_session()
    df = build_session(bars, NoiseBands(), PREV, or15_med=35.0)
    i = 100
    a5 = df["atr_5m"].iloc[i]
    close = df["close"].iloc[i]
    expected = (PREV["high"] - close) / a5
    assert np.isclose(df["pdh_dist_atr"].iloc[i], expected, rtol=1e-5)
