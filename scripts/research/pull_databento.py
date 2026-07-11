"""Pull MNQ front-month 1m bars 2023 -> mid-2025 from Databento GLBX.MDP3.

Per-contract RAW symbols on the app's own roll rule (expiry - 8 days,
app/feed/schwab_feed.front_month_symbol) so the calendar meshes exactly with
the existing oos_MNQU5/Z5/H6/M6 files. NEVER continuous symbology: its roll
schedule was measured to diverge (322-pt basis mismatches in roll weeks).

Also fills the 2025-06-11..15 gap where MNQU5 was already front but the
existing oos_MNQU5.json pull started late (written as oos_MNQU5_pre.json;
files are immutable once pulled — the data layer stitches and dedupes).

Usage:
    .venv/bin/python scripts/research/pull_databento.py --dry-run   # quote only
    .venv/bin/python scripts/research/pull_databento.py             # quote + pull
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

from app.config import HISTORY_DIR  # noqa: E402
from app.feed.schwab_feed import front_month_symbol  # noqa: E402

ET = ZoneInfo("America/New_York")
PULL_START = date(2023, 1, 1)
PULL_END = date(2025, 6, 15)  # existing oos_MNQU5.json takes over here


def db_symbol(schwab_sym: str) -> str:
    """'/MNQH23' -> Databento GLBX raw 'MNQH3' (single-digit year)."""
    s = schwab_sym.lstrip("/")
    return s[:-2] + s[-1]


def roll_windows() -> list[tuple[str, date, date]]:
    """(db_symbol, start, end_exclusive) windows that tile PULL_START..PULL_END.

    Stops before MNQU5: the existing oos_MNQU5/Z5/H6/M6 files own everything
    from there (immutable once pulled). The U5 gap window covers the two
    U5-front sessions (Jun 12/13 2025) missing from the existing U5 file.
    """
    windows: list[tuple[str, date, date]] = []
    d = PULL_START
    while d < PULL_END:
        sym = db_symbol(front_month_symbol(d))
        if sym == "MNQU5":
            break
        if windows and windows[-1][0] == sym:
            windows[-1] = (sym, windows[-1][1], d + timedelta(days=1))
        else:
            windows.append((sym, d, d + timedelta(days=1)))
        d += timedelta(days=1)
    windows.append(("MNQU5", date(2025, 6, 11), date(2025, 6, 15)))
    return windows


def owned(sym: str, bars: list[dict]) -> list[dict]:
    """Keep only bars in sessions this contract owns under the roll rule.

    Contracts overlap in real trading time around rolls; without this trim,
    two files would carry different prices at identical timestamps.
    """
    keep = []
    for b in bars:
        sd = session_key(b["time"])
        owner = db_symbol(front_month_symbol(date.fromisoformat(sd)))
        if owner == sym:
            keep.append(b)
    return keep


def session_key(ts: float) -> str:
    """18:00 ET rollover, mirroring app/engine/session.session_date."""
    et = datetime.fromtimestamp(ts, tz=ET)
    if et.hour >= 18:
        et += timedelta(days=1)
    return et.strftime("%Y-%m-%d")


def integrity(sym: str, bars: list[dict], prev_last_close: float | None) -> None:
    times = [b["time"] for b in bars]
    dups = len(times) - len(set(times))
    backward = sum(1 for a, b in zip(times, times[1:]) if b <= a)
    zerovol = sum(1 for b in bars if not b["volume"])
    sessions: dict[str, int] = {}
    for b in bars:
        sessions[session_key(b["time"])] = sessions.get(session_key(b["time"]), 0) + 1
    short = [s for s, n in sessions.items() if n < 200]
    lo = min(b["low"] for b in bars)
    hi = max(b["high"] for b in bars)
    gap = "" if prev_last_close is None else \
        f"  roll gap vs prev contract: {bars[0]['open'] - prev_last_close:+.2f} pts"
    print(f"  {sym}: {len(bars):>6} bars, {len(sessions):>3} sessions "
          f"({len(short)} short/holiday), range {lo:.0f}-{hi:.0f}, "
          f"dups={dups} backward={backward} zero-vol={zerovol}{gap}")
    if dups or backward:
        raise SystemExit(f"{sym}: integrity failure (dups/backward timestamps)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print cost quote and exit")
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    import databento as db
    client = db.Historical(os.getenv("DATABENTO_API_KEY"))

    windows = roll_windows()
    total = 0.0
    for sym, start, end in windows:
        total += client.metadata.get_cost(
            dataset="GLBX.MDP3", symbols=[sym], stype_in="raw_symbol",
            schema="ohlcv-1m", start=start.isoformat(), end=end.isoformat())
    print(f"{len(windows)} contract windows "
          f"{windows[0][1]}..{windows[-2][2]} + U5 gap fill; quote ${total:.2f}")
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
        bars = owned(sym, bars)
        if not bars:
            raise SystemExit(f"{sym}: empty response for {start}..{end}")
        suffix = "_pre" if sym == "MNQU5" else ""
        path = HISTORY_DIR / f"oos_{sym}{suffix}.json"
        path.write_text(json.dumps(bars))
        integrity(sym, bars, prev_close if not suffix else None)
        prev_close = bars[-1]["close"]
    print("done.")


if __name__ == "__main__":
    main()
