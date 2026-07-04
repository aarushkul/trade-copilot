"""Signal journal: SQLite persistence + hypothetical outcome tracking.

Every fired signal is tracked against the live tape as if it were taken:
- stop hit before target 1  -> STOPPED, full loss, counts toward circuit breaker
- target 1 hit, 1 contract  -> TARGET1, 1R win
- target 1 hit, 2 contracts -> half off at T1, runner to T2 with stop at breakeven
- timeout / session close   -> FLAT_EXIT at market

This is what makes the win-rate stats on the dashboard honest.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional

from app.config import POINT_VALUE, Settings
from app.engine.risk import CircuitBreaker
from app.engine.session import to_et
from app.models import Direction, Quote, Signal, SignalStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    day TEXT NOT NULL,
    direction TEXT NOT NULL,
    grade TEXT NOT NULL,
    score REAL NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target1 REAL NOT NULL,
    target2 REAL NOT NULL,
    contracts INTEGER NOT NULL,
    risk_dollars REAL NOT NULL,
    setup_type TEXT NOT NULL,
    reasons TEXT NOT NULL,
    status TEXT NOT NULL,
    resolved_ts REAL,
    exit_price REAL,
    pnl_dollars REAL,
    pnl_r REAL,
    mfe_points REAL DEFAULT 0,
    mae_points REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_signals_day ON signals(day);
"""


class Journal:
    def __init__(self, db_path: str | Path, settings: Settings,
                 breaker: CircuitBreaker):
        self.settings = settings
        self.breaker = breaker
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.open_signal: Optional[Signal] = None
        self._partial_banked: float = 0.0     # $ banked at T1 by the runner logic
        self._runner_stop: Optional[float] = None
        self.on_update: Optional[Callable[[Signal], None]] = None

    # -- recording ------------------------------------------------------------

    def record(self, signal: Signal) -> None:
        signal.status = SignalStatus.OPEN
        self.open_signal = signal
        self._partial_banked = 0.0
        self._runner_stop = None
        self._insert(signal)

    def _insert(self, s: Signal) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO signals
               (id, ts, day, direction, grade, score, entry, stop, target1,
                target2, contracts, risk_dollars, setup_type, reasons, status,
                resolved_ts, exit_price, pnl_dollars, pnl_r, mfe_points, mae_points)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (s.id, s.ts, _day(s.ts), s.direction.value, s.grade.value, s.score,
             s.entry, s.stop, s.target1, s.target2, s.contracts, s.risk_dollars,
             s.setup_type, json.dumps(s.reasons), s.status.value, s.resolved_ts,
             s.exit_price, s.pnl_dollars, s.pnl_r, s.mfe_points, s.mae_points))
        self.conn.commit()

    # -- live tracking -----------------------------------------------------------

    def on_quote(self, q: Quote) -> None:
        s = self.open_signal
        if s is None:
            return
        price = q.last
        sign = 1 if s.direction == Direction.LONG else -1

        # Excursions in points, positive = favourable.
        fav = (price - s.entry) * sign
        s.mfe_points = max(s.mfe_points, fav)
        s.mae_points = max(s.mae_points, -fav)

        stop = self._runner_stop if self._runner_stop is not None else s.stop
        stop_hit = (price <= stop) if sign == 1 else (price >= stop)
        t1_hit = (price >= s.target1) if sign == 1 else (price <= s.target1)
        t2_hit = (price >= s.target2) if sign == 1 else (price <= s.target2)

        if self._runner_stop is None:
            # Phase 1: full position, watching stop vs target 1.
            if stop_hit:
                self._resolve(q.ts, SignalStatus.STOPPED, stop,
                              pnl=-s.risk_dollars)
                return
            if t1_hit:
                r_per_contract = s.stop_points * POINT_VALUE
                if s.contracts == 1:
                    self._resolve(q.ts, SignalStatus.TARGET1, s.target1,
                                  pnl=r_per_contract)
                    return
                # Bank half at T1, run the rest with stop at breakeven.
                half = s.contracts // 2 or 1
                self._partial_banked = half * r_per_contract
                self._runner_stop = s.entry
                self._touch(s)
        else:
            # Phase 2: runner active with breakeven stop.
            runner = s.contracts - (s.contracts // 2 or 1)
            r_per_contract = s.stop_points * POINT_VALUE
            if t2_hit:
                self._resolve(q.ts, SignalStatus.TARGET2, s.target2,
                              pnl=self._partial_banked + runner * 2 * r_per_contract)
                return
            if stop_hit:
                self._resolve(q.ts, SignalStatus.FLAT_EXIT, s.entry,
                              pnl=self._partial_banked)
                return

        # Timeout or session end -> flat exit at market.
        age_min = (q.ts - s.ts) / 60.0
        if age_min >= self.settings.max_signal_age_min or _past_close(q.ts):
            runner_contracts = (s.contracts - (s.contracts // 2 or 1)
                                if self._runner_stop is not None else s.contracts)
            pnl = (self._partial_banked
                   + fav * POINT_VALUE * runner_contracts)
            self._resolve(q.ts, SignalStatus.FLAT_EXIT, price, pnl=pnl)

    def _resolve(self, ts: float, status: SignalStatus, exit_price: float,
                 pnl: float) -> None:
        s = self.open_signal
        if s is None:
            return
        s.status = status
        s.resolved_ts = ts
        s.exit_price = round(exit_price, 2)
        s.pnl_dollars = round(pnl, 2)
        s.pnl_r = round(pnl / s.risk_dollars, 2) if s.risk_dollars else 0.0
        if status == SignalStatus.STOPPED:
            self.breaker.record_stop_out(_day(ts))
        self._insert(s)
        self.open_signal = None
        self._runner_stop = None
        self._partial_banked = 0.0
        self._touch(s)

    def _touch(self, s: Signal) -> None:
        if self.on_update:
            self.on_update(s)

    # -- queries -----------------------------------------------------------------

    def recent(self, n: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM signals ORDER BY ts DESC LIMIT ?", (n,)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def stats(self, day: Optional[str] = None) -> dict:
        where, params = ("WHERE day = ?", (day,)) if day else ("", ())
        rows = self.conn.execute(
            f"SELECT status, pnl_dollars, pnl_r, setup_type FROM signals {where}",
            params).fetchall()
        resolved = [r for r in rows if r["status"] not in ("ACTIVE", "OPEN")]
        wins = [r for r in resolved if r["status"] in ("TARGET1", "TARGET2")]
        losses = [r for r in resolved if r["status"] == "STOPPED"]
        pnl = sum(r["pnl_dollars"] or 0 for r in resolved)
        rs = [r["pnl_r"] for r in resolved if r["pnl_r"] is not None]

        by_setup: dict[str, dict] = {}
        for r in resolved:
            b = by_setup.setdefault(r["setup_type"],
                                    {"count": 0, "wins": 0, "pnl": 0.0})
            b["count"] += 1
            b["pnl"] = round(b["pnl"] + (r["pnl_dollars"] or 0), 2)
            if r["status"] in ("TARGET1", "TARGET2"):
                b["wins"] += 1

        return {
            "signals": len(rows),
            "resolved": len(resolved),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(resolved) * 100, 1) if resolved else 0.0,
            "pnl_dollars": round(pnl, 2),
            "avg_r": round(sum(rs) / len(rs), 2) if rs else 0.0,
            "by_setup": by_setup,
        }

    def today_stats(self) -> dict:
        return self.stats(_day(time.time()))


def _day(ts: float) -> str:
    return to_et(ts).strftime("%Y-%m-%d")


def _past_close(ts: float) -> bool:
    dt = to_et(ts)
    return dt.hour >= 16 and dt.hour < 18


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["reasons"] = json.loads(d["reasons"])
    return d
