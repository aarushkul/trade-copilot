"""Forward (fwd_*) bracket targets — the ONLY place forward information lives.

Every column here answers: "if a signal fired at this bar's close, what net R
would the canonical sim-1 bracket have produced?" Canonical brackets per the
pre-registered specs (research/specs/tod.md, ml.md): stop 1.0 x atr_5m,
target in {1R, 2R}, horizon in {30, 60} minutes, both directions.

Semantics are an exact vectorized mirror of sim.resolve_bracket — the
equivalence test (tests/test_research_outcomes.py) compares them bar-by-bar.
Values are net R (Trade.r); NaN where no entry is possible (last bar, entry
bar at/after force-flat, atr not ready).

Cached to data/research/outcomes/v{OUTCOME_VERSION}/{split}.parquet, in a
separate tree from features on purpose: rule predicates and model inputs load
features; only target construction loads outcomes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import POINT_VALUE, TICK_SIZE
from app.models import Bar
from app.research.sim import (COMMISSION_PER_SIDE, FLAT_MINUTE_ET,
                              SLIPPAGE_TICKS)

OUTCOME_VERSION = 1

TARGET_RS = (1.0, 2.0)
HORIZONS_MIN = (30, 60)

OUTCOME_COLUMNS = [
    f"fwd_{side}_{int(tr)}r_{hz}m"
    for side in ("long", "short") for tr in TARGET_RS for hz in HORIZONS_MIN
]


def _minute_et_array(ts: np.ndarray) -> np.ndarray:
    et = pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York")
    return (et.hour * 60 + et.minute).to_numpy()


def _resolve_vector(o: np.ndarray, h: np.ndarray, l: np.ndarray,
                    c: np.ndarray, minute: np.ndarray, stop_pts: np.ndarray,
                    direction: int, target_r: float, horizon: int,
                    slip: float) -> np.ndarray:
    """Net R per signal bar for one (direction, target_r, horizon) arm.

    Mirrors sim.resolve_bracket exactly: entry next-bar open +/- slip, target
    needs 1-tick trade-through, stop/flat/horizon exits pay slip, both-in-bar
    scores a STOP, force-flat at FLAT_MINUTE_ET, run-off-data exits at the
    last close.
    """
    n = len(o)
    r = np.full(n, np.nan, dtype=np.float64)
    e = np.arange(n) + 1                                 # entry bar index
    e_clip = np.minimum(e, n - 1)
    valid = ((e < n) & np.isfinite(stop_pts) & (stop_pts > 0)
             & (minute[e_clip] < FLAT_MINUTE_ET))
    if not valid.any():
        return r

    idx = np.flatnonzero(valid)
    ei = e[idx]
    entry_px = o[ei] + direction * slip
    sp = stop_pts[idx]
    stop_px = entry_px - direction * sp
    target_px = entry_px + direction * sp * target_r
    exit_px = np.full(len(idx), np.nan)
    open_mask = np.ones(len(idx), dtype=bool)            # still unresolved

    for k in range(horizon + 1):
        j = ei + k
        act = open_mask & (j < n)
        if not act.any():
            break
        ja = j[act]
        exi = np.full(act.sum(), np.nan)
        flat = minute[ja] >= FLAT_MINUTE_ET
        hz = (~flat) & (k >= horizon)
        exi[flat | hz] = o[ja][flat | hz] - direction * slip
        live = ~(flat | hz)
        if direction > 0:
            stop_t = l[ja] <= stop_px[act]
            tgt_f = h[ja] >= target_px[act] + TICK_SIZE
        else:
            stop_t = h[ja] >= stop_px[act]
            tgt_f = l[ja] <= target_px[act] - TICK_SIZE
        stopd = live & stop_t                            # both-in-bar => STOP
        tgtd = live & tgt_f & ~stop_t
        exi[stopd] = stop_px[act][stopd] - direction * slip
        exi[tgtd] = target_px[act][tgtd]
        done = ~np.isnan(exi)
        ai = np.flatnonzero(act)[done]
        exit_px[ai] = exi[done]
        open_mask[ai] = False

    # ran off the end of the session's data: flat at last close
    exit_px[open_mask] = c[-1] - direction * slip

    pnl = (exit_px - entry_px) * direction * POINT_VALUE - 2 * COMMISSION_PER_SIDE
    r[idx] = pnl / (sp * POINT_VALUE)
    return r


def session_outcomes(bars: list[Bar], stop_pts: np.ndarray,
                     slippage_ticks: int = SLIPPAGE_TICKS) -> pd.DataFrame:
    """All OUTCOME_COLUMNS for one session. stop_pts must align with bars
    (features' atr_5m column — the canonical stop)."""
    o = np.array([b.open for b in bars])
    h = np.array([b.high for b in bars])
    l = np.array([b.low for b in bars])
    c = np.array([b.close for b in bars])
    minute = _minute_et_array(np.array([b.ts for b in bars]))
    slip = slippage_ticks * TICK_SIZE
    out = {}
    for side, direction in (("long", 1), ("short", -1)):
        for tr in TARGET_RS:
            for hz in HORIZONS_MIN:
                out[f"fwd_{side}_{int(tr)}r_{hz}m"] = _resolve_vector(
                    o, h, l, c, minute, np.asarray(stop_pts, dtype=np.float64),
                    direction, tr, hz, slip)
    return pd.DataFrame(out).astype(np.float32)


def _outcomes_dir():
    from app.config import DATA_DIR
    d = DATA_DIR / "research" / "outcomes" / f"v{OUTCOME_VERSION}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_all(verbose: bool = True) -> dict[str, int]:
    """Build outcome parquets from the corpus + the built feature store
    (features must exist first: stop_pts = features.atr_5m, guaranteeing the
    stop the targets assume is exactly the stop the rules will see).

    Reads feature parquets directly (not load_features): the builder is
    infrastructure, never inspects results, and must not consume looks.
    """
    from app.research import data as datamod
    from app.research.features import _features_dir

    all_sessions = datamod.sessions(include_roll=False)
    counts = {}
    out = _outcomes_dir()
    for split in ("train", "validation", "holdout"):
        fpath = _features_dir() / f"{split}.parquet"
        if not fpath.exists():
            if split == "train":
                raise FileNotFoundError(f"{fpath} — build features first")
            continue
        feats = pd.read_parquet(fpath)
        frames = []
        for sd, grp in feats.groupby("session", sort=True):
            bars = all_sessions.get(sd)
            if bars is None:
                raise RuntimeError(f"features contain unknown session {sd}")
            if len(grp) != len(bars):
                raise RuntimeError(
                    f"{sd}: {len(grp)} feature rows vs {len(bars)} bars")
            df = session_outcomes(bars, grp["atr_5m"].to_numpy(np.float64))
            # exact float64 ts from the bars (features' ts is float32);
            # row alignment with features is positional within a session
            df.insert(0, "ts", np.array([b.ts for b in bars]))
            df.insert(0, "session", sd)
            frames.append(df)
        full = pd.concat(frames, ignore_index=True)
        full.to_parquet(out / f"{split}.parquet", index=False)
        counts[split] = len(full)
        if verbose:
            print(f"  outcomes {split}: {len(full):,} rows")
    return counts


def load_outcomes(split: str, run_id: str | None = None) -> pd.DataFrame:
    """Split-fenced access, same guard as features.load_features."""
    from app.research import ledger, splits

    if split in ("validation", "holdout"):
        if not run_id:
            raise splits.SplitViolation(
                f"{split} outcomes require a ledger-registered run_id")
        reg = ledger.registration(run_id)
        if reg.get("split") != split:
            raise splits.SplitViolation(
                f"run_id {run_id} is for split {reg.get('split')!r}, not {split!r}")
    path = _outcomes_dir() / f"{split}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} — run scripts/research/build_features.py")
    return pd.read_parquet(path)
