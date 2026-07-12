"""Order-flow feature layer (research/specs/orderflow.md + addendum).

Turns the per-minute NQ proxy rows (buy_vol, sell_vol, n_secs from the 1s
tick rule) into causal per-bar columns aligned positionally with the v1
feature store, for sessions inside flow coverage. All columns are trailing
aggregates — the anti-lookahead truncation test applies unchanged.

Cached to data/research/flow/v1/{split}.parquet.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

FLOW_VERSION = 1
ET = ZoneInfo("America/New_York")
RTH_OPEN_MIN = 9 * 60 + 30
RTH_CLOSE_MIN = 16 * 60
RTH_MINUTES = RTH_CLOSE_MIN - RTH_OPEN_MIN

FLOW_COLUMNS = [
    "fl_delta", "fl_imbalance", "fl_delta_5m", "fl_imb_5m",
    "fl_delta_15m", "fl_imb_15m", "fl_cumdelta", "fl_cumdelta_div",
    "fl_active_vs_14d", "fl_absorption",
]

# fixed parameters of the fl_absorption ML column (rule grids re-derive
# their own thresholds from fl_imb_5m directly)
ABSORB_PROX_ATR = 0.25
ABSORB_IMB = 0.15


def _roll_sum(a: np.ndarray, w: int) -> np.ndarray:
    c = np.cumsum(np.nan_to_num(a))
    out = c.copy()
    out[w:] = c[w:] - c[:-w]
    return out


def build_session_flow(bars, flow_rows: pd.DataFrame | None,
                       atr5: np.ndarray, active_ref: np.ndarray | None
                       ) -> pd.DataFrame:
    """Flow columns for one session. flow_rows indexed by minute ts."""
    n = len(bars)
    ts = np.array([b.ts for b in bars])
    close = np.array([b.close for b in bars])
    low = np.array([b.low for b in bars])
    high = np.array([b.high for b in bars])
    out = {c: np.full(n, np.nan) for c in FLOW_COLUMNS}

    if flow_rows is None or flow_rows.empty:
        return pd.DataFrame(out).astype(np.float32)

    fr = flow_rows.set_index("ts")
    buy = fr["buy_vol"].reindex(ts).to_numpy()
    sell = fr["sell_vol"].reindex(ts).to_numpy()
    nsec = fr["n_secs"].reindex(ts).fillna(0).to_numpy()
    covered = np.isfinite(buy)
    buy = np.nan_to_num(buy)
    sell = np.nan_to_num(sell)

    delta = buy - sell
    tot = buy + sell
    out["fl_delta"] = np.where(covered, delta, np.nan)
    out["fl_imbalance"] = np.where(covered & (tot > 0), delta / np.maximum(tot, 1e-9), 0.0)
    d5, t5 = _roll_sum(delta, 5), _roll_sum(tot, 5)
    d15, t15 = _roll_sum(delta, 15), _roll_sum(tot, 15)
    out["fl_delta_5m"] = np.where(covered, d5, np.nan)
    out["fl_imb_5m"] = np.where(covered & (t5 > 0), d5 / np.maximum(t5, 1e-9), 0.0)
    out["fl_delta_15m"] = np.where(covered, d15, np.nan)
    out["fl_imb_15m"] = np.where(covered & (t15 > 0), d15 / np.maximum(t15, 1e-9), 0.0)
    cum = np.cumsum(delta)
    out["fl_cumdelta"] = np.where(covered, cum, np.nan)
    px_chg = close - close[0]
    out["fl_cumdelta_div"] = np.where(covered, np.sign(px_chg) * np.sign(cum), np.nan)

    # activity vs trailing 14-session same-minute reference (RTH only)
    et_min = np.array([datetime.fromtimestamp(t, tz=ET).hour * 60
                       + datetime.fromtimestamp(t, tz=ET).minute for t in ts])
    rth = (et_min >= RTH_OPEN_MIN) & (et_min < RTH_CLOSE_MIN)
    if active_ref is not None:
        rm = np.clip(et_min - RTH_OPEN_MIN, 0, RTH_MINUTES - 1)
        ref = active_ref[rm]
        ok = rth & covered & np.isfinite(ref) & (ref > 0)
        out["fl_active_vs_14d"] = np.where(ok, nsec / np.maximum(ref, 1e-9), np.nan)

    # absorption flag (fixed-parameter ML column)
    lo30 = pd.Series(low).rolling(30, min_periods=5).min().to_numpy()
    hi30 = pd.Series(high).rolling(30, min_periods=5).max().to_numpy()
    a5 = np.where(np.isfinite(atr5) & (atr5 > 0), atr5, np.nan)
    near_lo = (close - lo30) <= ABSORB_PROX_ATR * a5
    near_hi = (hi30 - close) <= ABSORB_PROX_ATR * a5
    imb5 = np.nan_to_num(out["fl_imb_5m"])
    absorb = np.where(near_lo & (imb5 >= ABSORB_IMB), 1.0,
                      np.where(near_hi & (imb5 <= -ABSORB_IMB), -1.0, 0.0))
    out["fl_absorption"] = np.where(covered & np.isfinite(a5), absorb, np.nan)

    return pd.DataFrame(out).astype(np.float32)


def session_active_profile(flow_rows: pd.DataFrame, bars) -> np.ndarray | None:
    """Per-minute-of-RTH active-seconds profile for the trailing reference."""
    if flow_rows is None or flow_rows.empty:
        return None
    prof = np.full(RTH_MINUTES, np.nan)
    fr = flow_rows.set_index("ts")
    got = 0
    for b in bars:
        et = datetime.fromtimestamp(b.ts, tz=ET)
        m = et.hour * 60 + et.minute
        if RTH_OPEN_MIN <= m < RTH_CLOSE_MIN and b.ts in fr.index:
            prof[m - RTH_OPEN_MIN] = fr.at[b.ts, "n_secs"]
            got += 1
    return prof if got >= 200 else None


def _flow_dir():
    from app.config import DATA_DIR
    d = DATA_DIR / "research" / "flow" / f"v{FLOW_VERSION}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_all(verbose: bool = True) -> dict[str, int]:
    """Walk covered sessions chronologically; write one parquet per split
    (only splits with covered sessions — currently train 2025)."""
    from app.config import HISTORY_DIR
    from app.engine.session import session_date
    from app.research import data as datamod
    from app.research import splits

    flow_raw = pd.read_parquet(HISTORY_DIR / "flow_NQ1s_2025.parquet")
    flow_raw["session"] = [session_date(t) for t in flow_raw["ts"]]
    by_session = dict(tuple(flow_raw.groupby("session")))

    all_sessions = datamod.sessions(include_roll=False)
    frames: dict[str, list[pd.DataFrame]] = {}
    active_hist: deque[np.ndarray] = deque(maxlen=14)
    for sd in sorted(all_sessions):
        fr = by_session.get(sd)
        if fr is None:
            continue
        bars = all_sessions[sd]
        # atr_5m recomputed from bars with the same helpers features.py uses
        # (identical values; avoids loading the full parquet per session)
        from app.research.features import _Composite, _Wilder
        atr5 = np.full(len(bars), np.nan)
        comp5, w5 = _Composite(5), _Wilder(14)
        prev5 = None
        for i, b in enumerate(bars):
            if comp5.push(b) and comp5.closed:
                o, h, l, c = comp5.closed
                tr = h - l if prev5 is None else max(h - l, abs(h - prev5), abs(l - prev5))
                w5.push(tr)
                prev5 = c
            atr5[i] = w5.v if w5.v else np.nan
        ref = (np.nanmean(np.stack(active_hist), axis=0)
               if active_hist else None)
        df = build_session_flow(bars, fr, atr5, ref)
        df.insert(0, "ts", np.array([b.ts for b in bars]))
        df.insert(0, "session", sd)
        frames.setdefault(splits.split_of(sd), []).append(df)
        prof = session_active_profile(fr, bars)
        if prof is not None:
            active_hist.append(prof)

    counts = {}
    out = _flow_dir()
    for split, fs in frames.items():
        full = pd.concat(fs, ignore_index=True)
        full.to_parquet(out / f"{split}.parquet", index=False)
        counts[split] = len(full)
        if verbose:
            print(f"  flow {split}: {len(full):,} rows, "
                  f"{full['session'].nunique()} sessions")
    return counts


def load_flow(split: str) -> pd.DataFrame:
    path = _flow_dir() / f"{split}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} — run scripts/research/build_flow.py")
    return pd.read_parquet(path)
