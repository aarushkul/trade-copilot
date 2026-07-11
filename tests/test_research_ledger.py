"""Ledger: registration-before-results, stable hashing, hard look budgets."""
import json

import pytest

from app.research import ledger


def _spec(family="orb", split="train", grid=None):
    return {"family": family, "spec_id": f"{family}_v1", "split": split,
            "hypothesis": "test hypothesis", "params_grid": grid or {"k": [1]}}


def test_registration_hits_disk_before_any_result(tmp_path):
    led = tmp_path / "ledger.jsonl"
    rid = ledger.register(_spec(), path=led)
    records = [json.loads(ln) for ln in led.read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["kind"] == "registration"
    assert records[0]["run_id"] == rid
    assert records[0]["spec_hash"].startswith("sha256:")


def test_register_requires_core_fields(tmp_path):
    led = tmp_path / "ledger.jsonl"
    with pytest.raises(ledger.LedgerError):
        ledger.register({"family": "orb", "split": "train"}, path=led)


def test_spec_hash_stable_across_key_order():
    assert ledger.canonical_hash({"a": 1, "b": [2, 3]}) == \
        ledger.canonical_hash({"b": [2, 3], "a": 1})
    assert ledger.canonical_hash({"a": 1}) != ledger.canonical_hash({"a": 2})


def test_result_requires_existing_registration(tmp_path):
    led = tmp_path / "ledger.jsonl"
    with pytest.raises(ledger.LedgerError):
        ledger.append_result("r-nope", {"k": 1}, {"pf": 1.0}, path=led)
    rid = ledger.register(_spec(), path=led)
    ledger.append_result(rid, {"k": 1}, {"pf": 1.31, "win_rate": 44.0},
                         gates={"train_pass": True}, path=led)
    kinds = [json.loads(ln)["kind"] for ln in led.read_text().splitlines()]
    assert kinds == ["registration", "result"]


def test_validation_budget_is_two_per_family(tmp_path):
    led = tmp_path / "ledger.jsonl"
    ledger.register(_spec(split="validation"), path=led)
    ledger.register(_spec(split="validation", grid={"k": [2]}), path=led)
    with pytest.raises(ledger.LookBudgetExhausted):
        ledger.register(_spec(split="validation", grid={"k": [3]}), path=led)
    # a different family has its own budget
    ledger.register(_spec(family="levels", split="validation"), path=led)


def test_holdout_budget_is_one_total(tmp_path):
    led = tmp_path / "ledger.jsonl"
    ledger.register(_spec(family="assembled", split="holdout"), path=led)
    with pytest.raises(ledger.LookBudgetExhausted):
        ledger.register(_spec(family="anything_else", split="holdout"), path=led)


def test_looks_remaining_arithmetic(tmp_path):
    led = tmp_path / "ledger.jsonl"
    assert ledger.looks_remaining("orb", path=led) == {"validation": 2, "holdout": 1}
    ledger.register(_spec(split="validation"), path=led)
    assert ledger.looks_remaining("orb", path=led)["validation"] == 1
