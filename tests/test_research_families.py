"""Unit tests for the Phase-2 study helpers (no data files needed)."""
import numpy as np
import pandas as pd
import pytest

from app.research import families
from app.research.families import regime, tod


def test_registry_resolves_all_names():
    assert families.get("regime").FAMILY == "regime"
    assert families.get("tod").FAMILY == "tod"
    with pytest.raises(KeyError):
        families.get("nope")


def test_regime_grid_is_the_registered_26():
    vs = regime.variants()
    assert len(vs) == 26
    assert len({tuple(sorted(v.items())) for v in vs}) == 26
    assert {v["detector"] for v in vs} == {"band_breach", "open_drive",
                                           "gap", "cumvol"}


def test_boot_diff_t_separates_obvious_groups():
    rng = np.random.default_rng(1)
    a = rng.normal(3.0, 1.0, 200)
    b = rng.normal(1.0, 1.0, 200)
    assert regime._boot_diff_t(a, b) > 5
    assert abs(regime._boot_diff_t(a, a)) < 1
    assert regime._boot_diff_t(a[:3], b) == 0.0   # too few sessions


def test_classify_band_breach_uses_max_streak_up_to_m():
    tab = pd.DataFrame([{
        "session": "2024-01-02", "year": "2024", "rth_close": 105.0,
        "ok_30": True, "close_30": 100.0, "atr5_30": 2.0,
        "drive_band_30": 1.2, "drive_atr_30": 1.5, "gap_30": 0.5,
        "cumvol_30": 1.1, "max_beyond_30": 6.0,
    }])
    t = regime._classify(tab, {"detector": "band_breach", "k": 5, "m": 30})
    assert bool(t["is_trend"].iloc[0]) is True
    assert t["direction"].iloc[0] == 1.0
    assert t["fwd_drift_atr"].iloc[0] == pytest.approx(2.5)
    t2 = regime._classify(tab, {"detector": "band_breach", "k": 10, "m": 30})
    assert bool(t2["is_trend"].iloc[0]) is False


def test_tod_boot_t_zero_mean_is_insignificant():
    rng = np.random.default_rng(2)
    assert abs(tod._boot_t(rng.normal(0, 1, 500))) < 2


# ---------------------------------------------------------------- levels_v2

def _lv2_session(closes, sd_minutes_start=570):
    from app.research.families.common import SessionData
    close = np.asarray(closes, float)
    n = len(close)
    nan = np.full(n, np.nan)
    return SessionData(
        bars=[None] * n,
        open=close.copy(), high=close + 1.0, low=close - 1.0, close=close,
        minute_et=np.arange(sd_minutes_start, sd_minutes_start + n, dtype=float),
        f={"pdh_dist_atr": nan, "pdl_dist_atr": nan, "pdc_dist_atr": nan,
           "onh_dist_atr": nan, "onl_dist_atr": nan,
           "atr_1m": np.full(n, 2.0), "atr_5m": np.full(n, 4.0),
           "rvol_1m": np.full(n, 2.0), "minute_et": None},
    )


def _lv2_data():
    # A (prior week, Wed): flat 20950, feeds week hi/lo; no rn level in range.
    a = _lv2_session([20950.0] * 120)
    # B (next ISO week, Mon): near 21000 from below (dist -2), flip #1 at
    # bar 40 (approach 30 bars back only 2 pts -> fails), sits at 21010,
    # flip #2 at bar 80 approached from +10 -> short through fires.
    closes = [20998.0] * 40 + [21010.0] * 40 + [20993.0] * 40
    b = _lv2_session(closes)
    return {"2024-01-03": a, "2024-01-08": b}


def test_levels_v2_registry_and_prep_classes():
    from app.research.families import levels_v2
    assert families.get("levels_v2").FAMILY == "levels_v2"
    prep = levels_v2._prep(_lv2_data())
    a_classes = {c for c, _, _ in prep["2024-01-03"]}
    b_classes = {c for c, _, _ in prep["2024-01-08"]}
    assert "pwh" not in a_classes and "pwl" not in a_classes  # corpus edge
    assert {"pwh", "pwl"} <= b_classes
    assert sum(1 for c, _, _ in prep["2024-01-08"] if c == "rn") == 1
    ib_events = [ev for c, _, ev in prep["2024-01-08"] if c == "ibl"]
    assert ib_events and all(i >= 60 for i, _ in ib_events[0])  # >=10:30 only


def test_levels_v2_touch_budget_and_stop_merge():
    from app.research.families import levels_v2
    data = _lv2_data()
    build = levels_v2.make_build(levels_v2._prep(data))
    base = {"levelset": "round", "approach": 2.5, "arm": "break25",
            "window": "rth", "stop_s": 0.5, "target_r": 1.0}
    m1, _, _, _, _ = build(data, {**base, "touch_n": 1})
    assert not m1["2024-01-08"][0].any() and not m1["2024-01-08"][1].any()
    m2, s2, _, _, _ = build(data, {**base, "touch_n": 2})
    sig_l, sig_s = m2["2024-01-08"]
    assert not sig_l.any()
    assert list(np.flatnonzero(sig_s)) == [80]
    assert s2["2024-01-08"][80] == pytest.approx(9.0)   # |dist|7 + 0.5*atr5
    m3, s3, _, _, _ = build(data, {**base, "levelset": "full", "touch_n": 2})
    assert list(np.flatnonzero(m3["2024-01-08"][1])) == [80]
    assert s3["2024-01-08"][80] == pytest.approx(6.0)   # ibl merge, min stop
