"""Pull ES front-month 1m bars for the xmkt family (research/specs/xmkt.md).

TRAIN WINDOW ONLY (2019-05-06 -> 2025-12-10): validation/holdout-period ES
is deliberately not pulled until a validation look is spent, keeping the
split fence physical for this family. Raw per-contract symbols on the
app's expiry-8d roll rule (identical quarterly calendar to MNQ); NEVER
continuous symbology. Files data/history/xmkt_ES*.json are immutable once
pulled. Cost pre-commitment: abort unless quote <= $25.

Usage:
    .venv/bin/python scripts/research/pull_xmkt_es.py --dry-run   # quote only
    .venv/bin/python scripts/research/pull_xmkt_es.py             # quote + pull
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

from app.config import HISTORY_DIR  # noqa: E402
from app.feed.schwab_feed import front_month_symbol  # noqa: E402
from scripts.research.pull_databento import (  # noqa: E402
    db_symbol, integrity, session_key,
)

PULL_START = date(2019, 5, 6)          # match the MNQ train corpus start
PULL_END = date(2025, 12, 11)          # TRAIN_END inclusive (2025-12-10)
COST_CAP = 25.0                        # pre-committed in the spec


def es_windows() -> list[tuple[str, date, date]]:
    windows: list[tuple[str, date, date]] = []
    d = PULL_START
    while d < PULL_END:
        sym = db_symbol(front_month_symbol(d, root="/ES"))
        if windows and windows[-1][0] == sym:
            windows[-1] = (sym, windows[-1][1], d + timedelta(days=1))
        else:
            windows.append((sym, d, d + timedelta(days=1)))
        d += timedelta(days=1)
    return windows


def owned_es(sym: str, bars: list[dict]) -> list[dict]:
    keep = []
    for b in bars:
        sd = session_key(b["time"])
        owner = db_symbol(front_month_symbol(date.fromisoformat(sd), root="/ES"))
        if owner == sym:
            keep.append(b)
    return keep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    import databento as db
    client = db.Historical(os.getenv("DATABENTO_API_KEY"))

    windows = es_windows()
    total = 0.0
    for sym, start, end in windows:
        total += client.metadata.get_cost(
            dataset="GLBX.MDP3", symbols=[sym], stype_in="raw_symbol",
            schema="ohlcv-1m", start=start.isoformat(), end=end.isoformat())
    print(f"{len(windows)} ES contract windows "
          f"{windows[0][1]}..{windows[-1][2]}; quote ${total:.2f}")
    if total > COST_CAP:
        raise SystemExit(f"quote ${total:.2f} exceeds the pre-committed "
                         f"${COST_CAP:.0f} cap — deferring to user decision")
    if args.dry_run:
        return

    prev_close: float | None = None
    for sym, start, end in windows:
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3", symbols=[sym], stype_in="raw_symbol",
            schema="ohlcv-1m", start=start.isoformat(), end=end.isoformat())
        df = data.to_df()
        bars = [{"time": ts.timestamp(), "open": r["open"], "high": r["high"],
                 "low": r["low"], "close": r["close"], "volume": int(r["volume"])}
                for ts, r in df.iterrows()]
        bars.sort(key=lambda b: b["time"])
        bars = owned_es(sym, bars)
        if not bars:
            raise SystemExit(f"{sym}: empty response for {start}..{end}")
        path = HISTORY_DIR / f"xmkt_{sym}.json"
        if path.exists():
            raise SystemExit(f"{path.name} already exists — pulled files are "
                             f"immutable; delete first if a re-pull is intended")
        path.write_text(json.dumps(bars))
        integrity(sym, bars, prev_close)
        prev_close = bars[-1]["close"]
    print("done.")


if __name__ == "__main__":
    main()
