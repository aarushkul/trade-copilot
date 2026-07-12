"""Pull NQ flow data per research/specs/orderflow.md (incl. pre-pull addendum).

Two pulls, both aggregated to per-minute rows in memory (raw never persisted):
  1. ohlcv-1s 2025-01-01..2025-12-10 -> tick-rule proxy buy/sell volume
     -> data/history/flow_NQ1s_2025.parquet (ts, contract, buy_vol,
        sell_vol, n_secs)
  2. trades 2025-11-10..2025-12-10 (proxy-validation month ONLY)
     -> data/history/flow_NQtrades_val.parquet (ts, buy_vol, sell_vol,
        n_trades)

Tick rule per 1s bar: sign(close-open); doji -> sign vs previous 1s close;
still flat -> volume split 50/50. Databento trades side: 'B' buy aggressor,
'A' sell aggressor (validated downstream vs positive delta-return corr).

Usage:
    .venv/bin/python scripts/research/pull_orderflow.py --dry-run
    .venv/bin/python scripts/research/pull_orderflow.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

from app.config import HISTORY_DIR  # noqa: E402
from app.feed.schwab_feed import front_month_symbol  # noqa: E402

PROXY_PATH = HISTORY_DIR / "flow_NQ1s_2025.parquet"
TRADES_VAL_PATH = HISTORY_DIR / "flow_NQtrades_val.parquet"
PROXY_START, PROXY_END = date(2025, 1, 1), date(2025, 12, 10)
VAL_START, VAL_END = date(2025, 11, 10), date(2025, 12, 10)
CHUNK_DAYS = 5
COST_ABORT = 60.0


def with_retries(fn, what: str, attempts: int = 12, wait: float = 20.0):
    """This machine's network flaps on a seconds-scale duty cycle."""
    for k in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if k == attempts:
                raise
            print(f"    {what}: attempt {k} failed ({type(exc).__name__}); "
                  f"retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)


def nq_symbol(d: date) -> str:
    s = front_month_symbol(d, root="/NQ").lstrip("/")
    return s[:-2] + s[-1]


def roll_windows(start: date, end: date) -> list[tuple[str, date, date]]:
    windows: list[tuple[str, date, date]] = []
    d = start
    while d < end:
        sym = nq_symbol(d)
        if windows and windows[-1][0] == sym:
            windows[-1] = (sym, windows[-1][1], d + timedelta(days=1))
        else:
            windows.append((sym, d, d + timedelta(days=1)))
        d += timedelta(days=1)
    return windows


def minute_of(index) -> np.ndarray:
    """Epoch-minute keys; as_unit('ns') guards against pandas building the
    index in us/s resolution (silent unit bug otherwise)."""
    ns = index.as_unit("ns").view("int64")
    return (ns // 60_000_000_000 * 60).astype("int64")


def agg_1s(df: pd.DataFrame) -> pd.DataFrame:
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    v = df["volume"].to_numpy().astype(np.float64)
    s = np.sign(c - o)
    prev_c = np.concatenate(([np.nan], c[:-1]))
    s2 = np.sign(c - prev_c)
    s = np.where(s != 0, s, np.where(np.isfinite(s2), s2, 0.0))
    buy = np.where(s > 0, v, np.where(s == 0, v / 2, 0.0))
    sell = np.where(s < 0, v, np.where(s == 0, v / 2, 0.0))
    g = pd.DataFrame({"ts": minute_of(df.index), "buy_vol": buy,
                      "sell_vol": sell}).groupby("ts")
    out = g.sum()
    out["n_secs"] = g.size()
    return out.reset_index()


def agg_trades(df: pd.DataFrame) -> pd.DataFrame:
    size = df["size"].to_numpy().astype(np.float64)
    side = df["side"].to_numpy()
    g = pd.DataFrame({"ts": minute_of(df.index),
                      "buy_vol": np.where(side == "B", size, 0.0),
                      "sell_vol": np.where(side == "A", size, 0.0)}).groupby("ts")
    out = g.sum()
    out["n_trades"] = g.size()
    return out.reset_index()


def pull(client, schema: str, windows, agg, out_path: Path) -> None:
    if out_path.exists():
        raise SystemExit(f"{out_path.name} exists — flow files are immutable")
    frames = []
    for sym, s, e in windows:
        d, rows = s, 0
        while d < e:
            ce = min(d + timedelta(days=CHUNK_DAYS), e)
            data = with_retries(
                lambda d=d, ce=ce, sym=sym: client.timeseries.get_range(
                    dataset="GLBX.MDP3", symbols=[sym], stype_in="raw_symbol",
                    schema=schema, start=d.isoformat(), end=ce.isoformat()),
                f"{schema} {sym} {d}")
            df = data.to_df()
            if len(df):
                a = agg(df)
                a["contract"] = sym
                frames.append(a)
                rows += len(a)
            d = ce
        print(f"  {schema} {sym}: {rows:,} minute rows", flush=True)
    flow = pd.concat(frames, ignore_index=True)
    flow = flow.sort_values("ts").drop_duplicates("ts", keep="first")
    flow.to_parquet(out_path, index=False)
    print(f"wrote {len(flow):,} minutes -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    import databento as db
    client = db.Historical(os.getenv("DATABENTO_API_KEY"))

    proxy_w = roll_windows(PROXY_START, PROXY_END)
    val_w = roll_windows(VAL_START, VAL_END)
    total = 0.0
    for schema, windows in (("ohlcv-1s", proxy_w), ("trades", val_w)):
        for sym, s, e in windows:
            total += with_retries(
                lambda sym=sym, s=s, e=e, schema=schema:
                client.metadata.get_cost(
                    dataset="GLBX.MDP3", symbols=[sym], stype_in="raw_symbol",
                    schema=schema, start=s.isoformat(), end=e.isoformat()),
                f"quote {schema} {sym}")
    print(f"total quote: ${total:.2f} "
          f"(1s {proxy_w[0][1]}..{proxy_w[-1][2]} + val trades "
          f"{val_w[0][1]}..{val_w[-1][2]})")
    if args.dry_run:
        return
    if total > COST_ABORT:
        raise SystemExit(f"quote ${total:.2f} exceeds abort cap ${COST_ABORT}")

    pull(client, "ohlcv-1s", proxy_w, agg_1s, PROXY_PATH)
    pull(client, "trades", val_w, agg_trades, TRADES_VAL_PATH)
    print("done.")


if __name__ == "__main__":
    main()
