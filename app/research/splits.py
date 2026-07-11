"""Train / validation / holdout boundaries as code — THE fence.

Every research loader classifies sessions through `split_of`; validation and
holdout bars can only be obtained through `load_sessions`, which demands a
ledger-registered run_id for the matching split (the registration itself
consumed a look). Loading fenced data without a registration is structurally
impossible short of bypassing this module, which research/README.md declares
void: such results do not count.

Boundaries (session_date keys, 18:00 ET rollover — app/engine/session.py):
  TRAIN       2023-01-01 .. 2025-12-10   new 2023-2025 pull + oos U5/Z5 files
  VALIDATION  2025-12-11 .. 2026-05-26   oos H6/M6 (~119 sessions, ≤2 looks/family)
  HOLDOUT     2026-05-27 .. forward      Schwab tape + walk-forward + live (1 look)
"""
from __future__ import annotations

import re
from pathlib import Path

from app.research import ledger

REPO_ROOT = Path(__file__).resolve().parents[2]

TRAIN_START = "2023-01-01"
TRAIN_END = "2025-12-10"
VALIDATION_START = "2025-12-11"
VALIDATION_END = "2026-05-26"
HOLDOUT_START = "2026-05-27"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SplitViolation(RuntimeError):
    pass


def split_of(session_date: str) -> str:
    """Classify a session_date string into exactly one split."""
    if not _DATE_RE.match(session_date or ""):
        raise ValueError(f"not an ISO session_date: {session_date!r}")
    if session_date < TRAIN_START:
        return "train"  # pre-2023 data, if ever pulled, only enlarges train
    if session_date <= TRAIN_END:
        return "train"
    if session_date <= VALIDATION_END:
        return "validation"
    return "holdout"


def load_sessions(split: str, run_id: str | None = None,
                  ledger_path: Path = ledger.LEDGER_PATH) -> dict:
    """The only sanctioned door to research bars, keyed by session_date.

    train: open. validation/holdout: requires a run_id whose ledger
    registration matches the requested split (registering consumed the look).
    """
    if split not in ledger.SPLITS:
        raise ValueError(f"unknown split {split!r}")
    if split in ("validation", "holdout"):
        if not run_id:
            raise SplitViolation(
                f"{split} data requires a ledger-registered run_id "
                f"(register the spec first; that consumes a look)")
        reg = ledger.registration(run_id, ledger_path)
        if reg.get("split") != split:
            raise SplitViolation(
                f"run_id {run_id} is registered for split "
                f"{reg.get('split')!r}, not {split!r}")

    from app.research import data  # deferred: heavy, and Phase 1 provides it
    sessions = data.sessions()
    picked = {sd: bars for sd, bars in sessions.items() if split_of(sd) == split}
    if not picked:
        raise SplitViolation(f"no sessions available for split {split!r}")
    return picked


def data_fingerprint(session_dates: list[str]) -> str:
    """Stable identity of a session set, recorded in registrations."""
    return ledger.canonical_hash(sorted(session_dates))
