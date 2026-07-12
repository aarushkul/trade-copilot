"""Weekly edge report from the live journal.

Slices resolved signals by setup, grade, hour and session so you can see where
the money actually went — with sample sizes, because a $200 pocket on n=3 is
noise, not an edge. Run it at the end of each week before changing anything.

Usage:
    .venv/bin/python scripts/edge_report.py            # last 7 days
    .venv/bin/python scripts/edge_report.py --days 30
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DB_FILE  # noqa: E402

ET = ZoneInfo("America/New_York")
RESOLVED = ("TARGET1", "TARGET2", "STOPPED", "FLAT_EXIT")


def bucket(rows: list[dict]) -> str:
    pnls = [r["pnl_dollars"] or 0.0 for r in rows]
    wins = [p for p in pnls if p > 0]
    gross_loss = -sum(p for p in pnls if p <= 0)
    pf = (f"{sum(wins) / gross_loss:.2f}" if gross_loss > 0 else "inf")
    flag = "  (n too small to act on)" if len(rows) < 20 else ""
    return (f"n={len(rows):<4} win%={100 * len(wins) / len(rows):5.1f} "
            f"exp=${sum(pnls) / len(rows):7.2f} PF={pf:<5} "
            f"pnl=${sum(pnls):8.2f}{flag}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--include-sim", action="store_true",
                    help="include sim-feed sessions (excluded by default)")
    args = ap.parse_args()

    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    cutoff = datetime.now().timestamp() - args.days * 86400
    cols = {r[1] for r in con.execute("PRAGMA table_info(signals)")}
    src = "" if (args.include_sim or "source" not in cols) \
        else "AND source = 'live' "
    rows = [dict(r) for r in con.execute(
        f"SELECT ts, setup_type, grade, status, pnl_dollars, pnl_r, "
        f"mfe_points, contracts "
        f"FROM signals WHERE ts > ? {src}AND status IN (?,?,?,?) ORDER BY ts",
        (cutoff, *RESOLVED))]
    if not rows:
        print(f"no resolved signals in the last {args.days} days")
        return

    print(f"=== Edge report: last {args.days} days, {len(rows)} resolved"
          f"{' (live only)' if src else ''} ===")
    print(f"total: {bucket(rows)}")

    for name, key in [
            ("setup", lambda r: r["setup_type"]),
            ("grade", lambda r: r["grade"]),
            ("hour (ET)", lambda r: f"{datetime.fromtimestamp(r['ts'], tz=ET).hour:02d}"),
            ("session", lambda r: datetime.fromtimestamp(r["ts"], tz=ET)
             .strftime("%a %m-%d"))]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[str(key(r))].append(r)
        print(f"\n-- by {name}")
        for k in sorted(groups):
            print(f"  {k:<12} {bucket(groups[k])}")

    pnls = sorted((r["pnl_dollars"] or 0.0 for r in rows), reverse=True)
    net = sum(pnls)
    top_k = max(1, len(pnls) // 10)
    top = sum(pnls[:top_k])
    print(f"\n-- management (measured 2026-07-09: hold to target beats banking"
          f" small — scalp brackets replayed PF 0.31-0.50)")
    share = f" = {top / net * 100:.0f}% of net P&L" if net > 0 else ""
    print(f"  top {top_k} trade(s) (best 10%): ${top:+,.0f}{share}")
    banked = 0.0
    for r in rows:
        cts = r["contracts"] or 1
        mfe = (r["mfe_points"] or 0.0) * 2.0 * cts
        banked += (50 - 4 * 0.74 * cts) if mfe >= 50 else (r["pnl_dollars"] or 0.0)
    print(f"  scalper tax: banking $50 whenever shown (fills generous to the "
          f"scalp) → ${banked:+,.0f} vs actual ${net:+,.0f} "
          f"(Δ ${banked - net:+,.0f})")

    stops = [r for r in rows if r["status"] == "STOPPED"]
    if stops:
        avg_stop = sum(-(r["pnl_dollars"] or 0) for r in stops) / len(stops)
        print(f"\nstops: {len(stops)} at avg ${avg_stop:.0f} each — "
              f"{len(stops) * avg_stop / 1200 * 100:.0f}% of a $1,200 account "
              f"went to stop-outs this period")


if __name__ == "__main__":
    main()
