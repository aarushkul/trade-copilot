"""Split fence: exact boundaries and guarded access to fenced data."""
import sys
import types

import pytest

from app.research import ledger, splits


def _spec(family="vwap_reversion", split="train"):
    return {"family": family, "spec_id": f"{family}_v1", "split": split,
            "hypothesis": "test", "params_grid": {"k": [1, 2]}}


def test_boundary_dates_exact():
    assert splits.split_of("2023-01-01") == "train"
    assert splits.split_of("2025-12-10") == "train"
    assert splits.split_of("2025-12-11") == "validation"
    assert splits.split_of("2026-05-26") == "validation"
    assert splits.split_of("2026-05-27") == "holdout"
    assert splits.split_of("2026-07-10") == "holdout"
    # pre-2023 data, if ever pulled, only enlarges train
    assert splits.split_of("2022-06-01") == "train"


def test_split_of_rejects_garbage():
    for bad in ("2026/05/27", "20260527", "", None, "2026-5-7"):
        with pytest.raises(ValueError):
            splits.split_of(bad)


@pytest.fixture()
def fake_data(monkeypatch):
    mod = types.ModuleType("app.research.data")
    mod.sessions = lambda: {
        "2024-03-04": ["train-bar"],
        "2026-01-15": ["validation-bar"],
        "2026-07-01": ["holdout-bar"],
    }
    monkeypatch.setitem(sys.modules, "app.research.data", mod)
    return mod


def test_train_needs_no_registration(tmp_path, fake_data):
    led = tmp_path / "ledger.jsonl"
    out = splits.load_sessions("train", ledger_path=led)
    assert set(out) == {"2024-03-04"}


def test_validation_without_run_id_is_a_violation(tmp_path, fake_data):
    led = tmp_path / "ledger.jsonl"
    with pytest.raises(splits.SplitViolation):
        splits.load_sessions("validation", ledger_path=led)


def test_validation_with_wrong_split_registration_is_a_violation(tmp_path, fake_data):
    led = tmp_path / "ledger.jsonl"
    rid = ledger.register(_spec(split="train"), path=led)
    with pytest.raises(splits.SplitViolation):
        splits.load_sessions("validation", run_id=rid, ledger_path=led)


def test_validation_with_registration_passes_guard(tmp_path, fake_data):
    led = tmp_path / "ledger.jsonl"
    rid = ledger.register(_spec(split="validation"), path=led)
    out = splits.load_sessions("validation", run_id=rid, ledger_path=led)
    assert set(out) == {"2026-01-15"}


def test_data_fingerprint_is_order_independent():
    a = splits.data_fingerprint(["2024-01-02", "2024-01-03"])
    b = splits.data_fingerprint(["2024-01-03", "2024-01-02"])
    assert a == b and a.startswith("sha256:")
