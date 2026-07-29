"""Family registry. Each module exposes FAMILY, SPEC_ID, HYPOTHESIS,
PARAMS_GRID and run(split, run_id) -> list[(params, metrics, gates)]."""
from __future__ import annotations

from importlib import import_module

FAMILY_NAMES = ("regime", "tod", "vwap_reversion", "orb",
                "trend_continuation", "levels", "levels_v2", "gap",
                "compression", "xmkt", "trend_harvest", "ml", "orderflow",
                "ml_flow")


def get(name: str):
    if name not in FAMILY_NAMES:
        raise KeyError(f"unknown family {name!r}; known: {FAMILY_NAMES}")
    if name == "ml":
        return import_module("app.research.ml.train")
    if name == "ml_flow":
        return import_module("app.research.ml.flow_track")
    return import_module(f"app.research.families.{name}")
