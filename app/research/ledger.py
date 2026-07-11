"""Append-only research ledger with look budgets.

Every evaluation is REGISTERED before its results are computed: the
registration record (spec, grid, split, data fingerprint) hits disk first,
so there is no way to run a grid, peek, and pretend it never happened.
Validation and holdout registrations consume a hard look budget.

Records are JSON lines in research/ledger.jsonl (committed to git).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = REPO_ROOT / "research" / "ledger.jsonl"

# Hard budgets, per research/README.md. Validation looks are counted per
# family; the holdout look is global (one for the assembled final system).
VALIDATION_LOOKS_PER_FAMILY = 2
HOLDOUT_LOOKS_TOTAL = 1

SPLITS = ("train", "validation", "holdout")


class LedgerError(RuntimeError):
    pass


class LookBudgetExhausted(LedgerError):
    pass


def canonical_hash(obj) -> str:
    """sha256 of canonical JSON — stable across dict key order."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 - ledger must work outside git too
        return "unknown"


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def looks_used(family: str, split: str, path: Path = LEDGER_PATH) -> int:
    return sum(1 for r in _read(path)
               if r.get("kind") == "registration" and r.get("split") == split
               and (split == "holdout" or r.get("family") == family))


def looks_remaining(family: str, path: Path = LEDGER_PATH) -> dict[str, int]:
    return {
        "validation": VALIDATION_LOOKS_PER_FAMILY - looks_used(family, "validation", path),
        "holdout": HOLDOUT_LOOKS_TOTAL - looks_used(family, "holdout", path),
    }


def register(spec: dict, path: Path = LEDGER_PATH) -> str:
    """Write a registration record and return its run_id.

    `spec` must carry: family, spec_id, split, hypothesis, params_grid.
    For validation/holdout splits this consumes a look — budget exhaustion
    raises before anything is written.
    """
    missing = [k for k in ("family", "spec_id", "split", "hypothesis", "params_grid")
               if k not in spec]
    if missing:
        raise LedgerError(f"spec missing required fields: {missing}")
    split = spec["split"]
    if split not in SPLITS:
        raise LedgerError(f"unknown split {split!r}")

    if split == "validation":
        used = looks_used(spec["family"], "validation", path)
        if used >= VALIDATION_LOOKS_PER_FAMILY:
            raise LookBudgetExhausted(
                f"family {spec['family']!r} has used all "
                f"{VALIDATION_LOOKS_PER_FAMILY} validation looks")
    elif split == "holdout":
        if looks_used("*", "holdout", path) >= HOLDOUT_LOOKS_TOTAL:
            raise LookBudgetExhausted("the single holdout look is already spent")

    spec_hash = canonical_hash(spec)
    ts = datetime.now(timezone.utc)
    run_id = f"r-{ts:%Y%m%d-%H%M%S}-{spec_hash[7:15]}"
    _append(path, {
        "kind": "registration",
        "run_id": run_id,
        "ts_utc": ts.isoformat(),
        "git_sha": _git_sha(),
        "spec_hash": spec_hash,
        **spec,
    })
    return run_id


def registration(run_id: str, path: Path = LEDGER_PATH) -> dict:
    for r in _read(path):
        if r.get("kind") == "registration" and r.get("run_id") == run_id:
            return r
    raise LedgerError(f"run_id {run_id!r} is not registered")


def append_result(run_id: str, params: dict, metrics: dict,
                  gates: dict | None = None, path: Path = LEDGER_PATH) -> None:
    registration(run_id, path)  # must exist on disk first
    _append(path, {
        "kind": "result",
        "run_id": run_id,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "params": params,
        "metrics": metrics,
        "gates": gates or {},
    })
