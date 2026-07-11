"""The learning loop (Phase 7 machinery, cycle-aware).

Run weekly/monthly. In the current no-survivor state its job is to keep the
evidence base growing and report readiness — NOT to trade:

  1. --extend    fetch recent /MNQ 1m bars from Schwab and merge them into
                 data/history/mnq_1m_walkforward.json (new sessions land in
                 the holdout region and become future-cycle unseen data)
  2. rebuild the feature + outcome stores over the full corpus
  3. print a status report: corpus by split, accumulation since the cycle-1
     verdict, unspent look budgets, and what would trigger the next cycle

Usage:
    .venv/bin/python scripts/research/retrain.py --extend     # full loop
    .venv/bin/python scripts/research/retrain.py              # no fetch
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

WALKFORWARD = Path(__file__).resolve().parents[2] / "data" / "history" / "mnq_1m_walkforward.json"
VERDICT_DATE = "2026-07-11"      # cycle-1 verdict; accumulation counts from here


def extend_walkforward() -> None:
    from app.config import SchwabCredentials
    from app.feed.schwab_feed import SchwabFeed

    creds = SchwabCredentials()
    if not creds.configured:
        print("Schwab credentials not configured; skipping fetch")
        return
    existing = json.loads(WALKFORWARD.read_text()) if WALKFORWARD.exists() else []
    last_ts = max((b["time"] for b in existing), default=0.0)
    gap_days = min(35, max(2, int((time.time() - last_ts) / 86400) + 2)) if last_ts else 35
    print(f"fetching ~{gap_days} days of /MNQ 1m bars from Schwab...")
    feed = SchwabFeed(creds)
    bars = feed.fetch_history(days=gap_days)
    if not bars:
        print("fetch returned nothing; walk-forward file unchanged")
        return
    by_ts = {b["time"]: b for b in existing}
    added = 0
    for b in bars:
        if b.ts not in by_ts:
            added += 1
        by_ts[b.ts] = {"time": b.ts, "open": b.open, "high": b.high,
                       "low": b.low, "close": b.close, "volume": b.volume}
    merged = [by_ts[t] for t in sorted(by_ts)]
    WALKFORWARD.write_text(json.dumps(merged))
    print(f"walk-forward file: +{added:,} new bars -> {len(merged):,} total")


def rebuild_stores() -> None:
    from app.research import outcomes
    from app.research.features import build_all

    t0 = time.time()
    build_all(verbose=False)
    outcomes.build_all(verbose=False)
    print(f"feature + outcome stores rebuilt in {time.time() - t0:.0f}s")


def status() -> None:
    from app.research import data as datamod
    from app.research import ledger, splits

    meta = datamod.session_meta()
    by_split: dict[str, int] = {}
    accumulated = 0
    for sd, m in meta.items():
        if m.is_roll:
            continue
        s = splits.split_of(sd)
        by_split[s] = by_split.get(s, 0) + 1
        if s == "holdout" and sd > VERDICT_DATE:
            accumulated += 1

    print("\n=== learning-loop status", date.today().isoformat(), "===")
    print(f"corpus (usable sessions): {by_split}")
    print(f"holdout-region sessions accumulated since cycle-1 verdict "
          f"({VERDICT_DATE}): {accumulated}")
    for fam in ("vwap_reversion", "orb", "trend_continuation", "levels", "ml"):
        looks = ledger.looks_remaining(fam)
        print(f"  {fam}: validation looks left {looks['validation']}, "
              f"holdout look left {looks['holdout']}")
    print("state: NO SURVIVORS from cycles 1/1b -> no live signal-trading.")
    print("next cycle triggers: (a) a materially new hypothesis registered "
          "before evaluation, or (b) enough fresh unseen sessions for a new "
          "validation window (~60+) once a train survivor exists.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extend", action="store_true",
                    help="fetch recent bars from Schwab before rebuilding")
    ap.add_argument("--skip-rebuild", action="store_true")
    args = ap.parse_args()
    if args.extend:
        extend_walkforward()
    if not args.skip_rebuild:
        rebuild_stores()
    status()


if __name__ == "__main__":
    main()
