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


# ---------------------------------------------------------------------- gap

def _gap_session(pdc_path, on_prefix=30):
    """Overnight prefix then RTH bars; pdc_dist_atr follows pdc_path."""
    from app.research.families.common import SessionData
    n_on = on_prefix
    n = n_on + len(pdc_path)
    close = np.full(n, 21000.0)
    pdc = np.concatenate([np.full(n_on, np.nan), np.asarray(pdc_path, float)])
    minute = np.concatenate([np.arange(1080, 1080 + n_on, dtype=float),
                             np.arange(570, 570 + len(pdc_path), dtype=float)])
    return SessionData(
        bars=[None] * n,
        open=close.copy(), high=close + 1, low=close - 1, close=close,
        minute_et=minute,
        f={"pdc_dist_atr": pdc, "atr_1m": np.full(n, 2.0),
           "atr_5m": np.full(n, 8.0), "rvol_1m": np.full(n, 2.0),
           "minute_et": None},
    )


def test_gap_arms_direction_and_fill_filter():
    from app.research.families import gap
    assert families.get("gap").FAMILY == "gap"
    up_unfilled = _gap_session([2.0] * 40)            # gap +2 atr, never fills
    up_filled = _gap_session([2.0] + [0.3] * 39)      # fills fast
    big = _gap_session([5.0] * 40)                    # beyond gcap 4.0
    data = {"2024-01-08": up_unfilled, "2024-01-09": up_filled,
            "2024-01-10": big}
    base = {"gmin": 1.0, "gcap": 4.0, "delay": 15, "stop_s": 1.0,
            "target_r": 1.0, "horizon": 60}
    build = gap.make_build()
    m, s, tr, hz, w = build(data, {**base, "arm": "fade"})
    sig_l, sig_s = m["2024-01-08"]
    assert list(np.flatnonzero(sig_s)) == [45]        # on_prefix 30 + delay 15
    assert not sig_l.any()
    assert s["2024-01-08"][45] == pytest.approx(8.0)  # 1.0 x atr5
    assert not m["2024-01-09"][1].any()               # filled -> no signal
    assert not m["2024-01-10"][1].any()               # gcap excludes
    m2, _, _, _, _ = build(data, {**base, "arm": "go"})
    assert list(np.flatnonzero(m2["2024-01-08"][0])) == [45]  # long with gap
    m3, _, _, _, _ = build(data, {**base, "arm": "go", "gcap": 999})
    assert m3["2024-01-10"][0].any()                  # uncapped includes big


# -------------------------------------------------------------- compression

def _coil_session(n=120, coil_break_at=60, rth_range=10.0):
    from app.research.families.common import SessionData
    close = np.full(n, 21000.0)
    high = close + rth_range / 2
    low = close - rth_range / 2
    if coil_break_at is not None:
        high = close + 1.0
        low = close - 1.0
        close = close.copy()
        close[coil_break_at:] = 21010.0
        high = np.maximum(high, close + 1.0)
        low = np.minimum(low, close - 1.0)
    return SessionData(
        bars=[None] * n,
        open=close.copy(), high=high, low=low, close=close,
        minute_et=np.arange(570, 570 + n, dtype=float),
        f={"atr_1m": np.full(n, 2.0), "atr_5m": np.full(n, 8.0),
           "rvol_1m": np.full(n, 2.0), "minute_et": None},
    )


def test_compression_break_stop_and_rearm():
    from app.research.families import compression
    assert families.get("compression").FAMILY == "compression"
    data = {"2024-01-08": _coil_session()}
    prep = compression._prep(data)
    build = compression.make_build(prep)
    p = {"nr_k": "none", "m": 20, "c": 1.5, "break_b": 0.0,
         "window": "rth", "stop_s": 0.5, "target_r": 1.0}
    m, s, _, _, _ = build(data, p)
    sig_l, sig_s = m["2024-01-08"]
    hits = list(np.flatnonzero(sig_l))
    assert hits and hits[0] == 60                    # break bar
    assert all(b - a >= 20 for a, b in zip(hits, hits[1:]))  # re-arm gap
    assert not sig_s.any()
    # stop = close - coilmin + 0.5*atr5 = 21010 - 20999 + 4 = 15
    assert s["2024-01-08"][60] == pytest.approx(15.0)


def test_compression_nr_conditioner_needs_k_priors():
    from app.research.families import compression
    # 4 wide-range priors then a narrow prior, then the coil session
    data = {f"2024-01-0{i}": _coil_session(coil_break_at=None, rth_range=30.0)
            for i in range(1, 5)}
    data["2024-01-05"] = _coil_session(coil_break_at=None, rth_range=4.0)
    data["2024-01-08"] = _coil_session()
    prep = compression._prep(data)
    assert 4 in prep["2024-01-08"]                   # narrow prior of last 4
    assert 7 not in prep["2024-01-08"]               # only 5 priors exist
    build = compression.make_build(prep)
    p = {"nr_k": 7, "m": 20, "c": 1.5, "break_b": 0.0,
         "window": "rth", "stop_s": 0.5, "target_r": 1.0}
    m, _, _, _, _ = build(data, p)
    assert not m["2024-01-08"][0].any()              # k=7 not qualified
    p4 = {**p, "nr_k": 4}
    m4, _, _, _, _ = build(data, p4)
    assert m4["2024-01-08"][0].any()                 # k=4 qualified
