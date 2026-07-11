"""Research session store: stitch per-contract history files into one
session-keyed corpus with contract-ownership enforcement.

Sources (data/history/):
  oos_MNQ*.json          per-contract front-month pulls (Databento)
  mnq_1m.json,
  mnq_1m_walkforward.json  Schwab front-month tape (holdout era, contract "SCHWAB")

Around quarterly rolls two contracts trade simultaneously and the older
files were pulled on UTC-midnight windows, so one session can carry bars
from both. Rule: a session belongs to the contract that was front month on
its session_date (expiry - 8 days, app/feed/schwab_feed.front_month_symbol);
bars from any other contract are dropped, and sessions that lost bars or
look truncated are flagged `is_roll` (excluded by default — ~4/year).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import HISTORY_DIR
from app.engine.session import session_date
from app.feed.schwab_feed import front_month_symbol
from app.models import Bar
from app.research.splits import HOLDOUT_START

SCHWAB_FILES = ("mnq_1m.json", "mnq_1m_walkforward.json")
# a normal Globex session has ~1,380 minute bars; half days ~1,000
MIN_FULL_SESSION_BARS = 800
ET = ZoneInfo("America/New_York")
LATE_OPEN_GRACE_SEC = 1800  # first bar >30 min after the 18:00 ET open = partial


def _opens_late(sd: str, first_ts: float) -> bool:
    """True when a session's first bar misses the 18:00 ET Globex open —
    session-anchored features (VWAP) would silently anchor wrong."""
    open_dt = datetime.combine(date.fromisoformat(sd) - timedelta(days=1),
                               time(18, 0), tzinfo=ET)
    return first_ts - open_dt.timestamp() > LATE_OPEN_GRACE_SEC


@dataclass
class SessionMeta:
    contract: str
    n_bars: int
    dropped_bars: int
    is_roll: bool


def _owner(sd: str) -> str:
    """Which source owns a session: the front-month contract, except the
    Schwab tape owns the holdout era outright (it IS the front month there,
    and the M6 pull's trailing overnight bars must not bleed across)."""
    if sd >= HOLDOUT_START:
        return "SCHWAB"
    sym = front_month_symbol(date.fromisoformat(sd)).lstrip("/")
    return sym[:-2] + sym[-1]


def _load_file(path: Path) -> list[dict]:
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def _corpus() -> tuple[dict, dict]:
    """(sessions: {sd: [Bar]}, meta: {sd: SessionMeta}) — built once."""
    raw: dict[str, dict[float, tuple[str, dict]]] = {}  # sd -> ts -> (contract, bar)
    dropped: dict[str, int] = {}

    for path in sorted(HISTORY_DIR.glob("oos_MNQ*.json")):
        contract = path.stem.replace("oos_", "").replace("_pre", "")
        for b in _load_file(path):
            sd = session_date(b["time"])
            if _owner(sd) != contract:
                dropped[sd] = dropped.get(sd, 0) + 1
                continue
            raw.setdefault(sd, {})[b["time"]] = (contract, b)

    for name in SCHWAB_FILES:
        path = HISTORY_DIR / name
        if not path.exists():
            continue
        for b in _load_file(path):
            sd = session_date(b["time"])
            if _owner(sd) != "SCHWAB":
                dropped[sd] = dropped.get(sd, 0) + 1
                continue
            raw.setdefault(sd, {})[b["time"]] = ("SCHWAB", b)  # dedupes overlap by ts

    sessions: dict[str, list[Bar]] = {}
    meta: dict[str, SessionMeta] = {}
    for sd in sorted(raw):
        by_ts = raw[sd]
        contracts = {c for c, _ in by_ts.values()}
        if len(contracts) != 1:
            raise RuntimeError(f"session {sd}: bars from {contracts} after ownership trim")
        bars = [Bar(t, b["open"], b["high"], b["low"], b["close"], int(b["volume"]))
                for t, (_, b) in sorted(by_ts.items())]
        contract = next(iter(contracts))
        is_roll = (dropped.get(sd, 0) > 0
                   or (contract != "SCHWAB" and len(bars) < MIN_FULL_SESSION_BARS)
                   or (contract != "SCHWAB" and _opens_late(sd, bars[0].ts)))
        sessions[sd] = bars
        meta[sd] = SessionMeta(contract, len(bars), dropped.get(sd, 0), is_roll)
    return sessions, meta


def sessions(include_roll: bool = False) -> dict[str, list[Bar]]:
    """All sessions keyed by session_date, roll sessions excluded by default."""
    sess, meta = _corpus()
    if include_roll:
        return dict(sess)
    return {sd: bars for sd, bars in sess.items() if not meta[sd].is_roll}


def session_meta() -> dict[str, SessionMeta]:
    return dict(_corpus()[1])
