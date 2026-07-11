"""Family registry. Each module exposes FAMILY, SPEC_ID, HYPOTHESIS,
PARAMS_GRID and run(split, run_id) -> list[(params, metrics, gates)]."""
from __future__ import annotations

from importlib import import_module

FAMILY_NAMES = ("regime", "tod", "vwap_reversion", "orb",
                "trend_continuation", "levels")


def get(name: str):
    if name not in FAMILY_NAMES:
        raise KeyError(f"unknown family {name!r}; known: {FAMILY_NAMES}")
    return import_module(f"app.research.families.{name}")
