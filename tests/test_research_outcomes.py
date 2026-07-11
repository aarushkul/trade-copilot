"""outcomes.py must be an exact vectorized mirror of sim.resolve_bracket."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from app.models import Bar
from app.research import sim
from app.research.outcomes import (HORIZONS_MIN, OUTCOME_COLUMNS, TARGET_RS,
                                   session_outcomes)

ET = ZoneInfo("America/New_York")


def synthetic_session(seed: int, n: int = 420) -> list[Bar]:
    """Random walk from 09:00 ET so bars straddle the 15:59 force-flat."""
    rng = np.random.default_rng(seed)
    start = datetime(2024, 3, 5, 9, 0, tzinfo=ET)
    px = 18000.0
    bars = []
    for i in range(n):
        o = px
        c = px + float(rng.normal(0, 5))
        h = max(o, c) + abs(float(rng.normal(0, 2)))
        l = min(o, c) - abs(float(rng.normal(0, 2)))
        bars.append(Bar((start + timedelta(minutes=i)).timestamp(),
                        round(o, 2), round(h, 2), round(l, 2), round(c, 2),
                        int(rng.integers(50, 500))))
        px = c
    return bars


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_equivalence_with_resolve_bracket(seed):
    bars = synthetic_session(seed)
    rng = np.random.default_rng(seed + 100)
    stop_pts = rng.uniform(5.0, 20.0, size=len(bars))
    df = session_outcomes(bars, stop_pts)
    assert list(df.columns) == OUTCOME_COLUMNS

    for i in rng.integers(0, len(bars), size=60):
        i = int(i)
        for side, direction in (("long", 1), ("short", -1)):
            for tr in TARGET_RS:
                for hz in HORIZONS_MIN:
                    col = f"fwd_{side}_{int(tr)}r_{hz}m"
                    got = df[col].iloc[i]
                    ref = sim.resolve_bracket(
                        bars, i, direction, float(stop_pts[i]),
                        float(stop_pts[i]) * tr, hz, session="t")
                    if ref is None:
                        assert np.isnan(got), f"{col} bar {i}: {got} vs None"
                    else:
                        assert got == pytest.approx(ref.r, abs=1e-6), \
                            f"{col} bar {i}: {got} vs {ref.r} ({ref.exit_reason})"


def test_invalid_stop_is_nan():
    bars = synthetic_session(9)
    stop_pts = np.full(len(bars), np.nan)
    stop_pts[10] = 0.0
    df = session_outcomes(bars, stop_pts)
    assert df[OUTCOME_COLUMNS].isna().all().all()


def test_every_outcome_column_is_forward_prefixed():
    assert all(c.startswith(sim.FORWARD_PREFIX) for c in OUTCOME_COLUMNS)
    with pytest.raises(ValueError):
        sim.assert_causal(OUTCOME_COLUMNS[:1])
