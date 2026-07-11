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
