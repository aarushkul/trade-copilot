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

from app.config import POINT_VALUE, TICK_VALUE, Settings
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
    mae_points REAL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'live'
);
CREATE INDEX IF NOT EXISTS idx_signals_day ON signals(day);
"""


class Journal:
    def __init__(self, db_path: str | Path, settings: Settings,
                 breaker: CircuitBreaker, source: str = "live"):
        self.settings = settings
        self.breaker = breaker
        # 'live' or 'sim': one journal instance operates in one world, so sim
        # test sessions can never pollute live stats or the circuit breaker.
        self.source = source
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(signals)")}
        if "source" not in cols:   # additive migration for pre-existing DBs
            self.conn.execute("ALTER TABLE signals ADD COLUMN source TEXT "
                              "NOT NULL DEFAULT 'live'")
            self.conn.commit()
        self.open_signal: Optional[Signal] = None
        self._partial_banked: float = 0.0     # $ banked at T1 by the runner logic
        self._runner_stop: Optional[float] = None
        self.on_update: Optional[Callable[[Signal], None]] = None
        self._recover_state()

    def _recover_state(self) -> None:
        """Startup hygiene after a restart.

        1. Signals left OPEN/ACTIVE by a previous run can't be tracked honestly
           any more -> mark EXPIRED_UNFILLED (excluded from win-rate stats).
        2. Re-seed the circuit breaker with today's stop-outs so a restart
           cannot bypass the daily lockout.
        """
        self.conn.execute(
            "UPDATE signals SET status = ? WHERE status IN ('OPEN', 'ACTIVE')",
            (SignalStatus.EXPIRED_UNFILLED.value,))
        self.conn.commit()
        today = _day(time.time())
        row = self.conn.execute(
            "SELECT COUNT(*) FROM signals WHERE day = ? AND status = 'STOPPED' "
            "AND source = ?", (today, self.source)).fetchone()
        if row and row[0]:
            self.breaker.seed(today, int(row[0]))

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
                resolved_ts, exit_price, pnl_dollars, pnl_r, mfe_points,
                mae_points, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (s.id, s.ts, _day(s.ts), s.direction.value, s.grade.value, s.score,
             s.entry, s.stop, s.target1, s.target2, s.contracts, s.risk_dollars,
             s.setup_type, json.dumps(s.reasons), s.status.value, s.resolved_ts,
             s.exit_price, s.pnl_dollars, s.pnl_r, s.mfe_points, s.mae_points,
             self.source))
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

        # P&L is computed from actual exit prices (not assumed R multiples),
        # so the journal stays honest under any bracket geometry.
        def pts(price_out: float) -> float:
            return (price_out - s.entry) * sign * POINT_VALUE

        if self._runner_stop is None:
            # Phase 1: full position, watching stop vs target 1.
            if stop_hit:
                self._resolve(q.ts, SignalStatus.STOPPED, stop,
                              pnl=s.contracts * pts(stop))
                return
            if t1_hit:
                if s.contracts == 1:
                    self._resolve(q.ts, SignalStatus.TARGET1, s.target1,
                                  pnl=pts(s.target1))
                    return
                # Bank half at T1, run the rest with stop at breakeven.
                half = s.contracts // 2 or 1
                self._partial_banked = half * pts(s.target1)
                self._runner_stop = s.entry
                self._touch(s)
        else:
            # Phase 2: runner active with breakeven stop.
            runner = s.contracts - (s.contracts // 2 or 1)
            if t2_hit:
                self._resolve(q.ts, SignalStatus.TARGET2, s.target2,
                              pnl=self._partial_banked + runner * pts(s.target2))
                return
            if stop_hit:
                self._resolve(q.ts, SignalStatus.FLAT_EXIT, self._runner_stop,
                              pnl=self._partial_banked
                                  + runner * pts(self._runner_stop))
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
        s.pnl_dollars = round(pnl - self._friction(s, status), 2)
        s.pnl_r = round(pnl / s.risk_dollars, 2) if s.risk_dollars else 0.0
        if status == SignalStatus.STOPPED:
            self.breaker.record_stop_out(_day(ts))
        self._insert(s)
        self.open_signal = None
        self._runner_stop = None
        self._partial_banked = 0.0
        self._touch(s)

    def _friction(self, s: Signal, status: SignalStatus) -> float:
        """Commissions + slippage for the whole round trip, in dollars.

        Entries and stop/flat exits are market-order fills (slip against you);
        target fills are resting limits (no slip modeled).
        """
        commissions = s.contracts * 2 * self.settings.commission_per_side
        slip_per_fill = self.settings.slippage_ticks * TICK_VALUE
        market_fills = s.contracts  # entry legs
        if status == SignalStatus.STOPPED:
            market_fills += s.contracts
        elif status == SignalStatus.FLAT_EXIT:
            runner = s.contracts - (s.contracts // 2 or 1)
            market_fills += runner if self._runner_stop is not None else s.contracts
        return commissions + market_fills * slip_per_fill

    def _touch(self, s: Signal) -> None:
        if self.on_update:
            self.on_update(s)

    # -- queries -----------------------------------------------------------------

    def recent(self, n: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM signals WHERE source = ? ORDER BY ts DESC LIMIT ?",
            (self.source, n)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def stats(self, day: Optional[str] = None) -> dict:
        where, params = (("WHERE source = ? AND day = ?", (self.source, day))
                         if day else ("WHERE source = ?", (self.source,)))
        rows = self.conn.execute(
            f"SELECT status, pnl_dollars, pnl_r, setup_type FROM signals {where}",
            params).fetchall()
        # EXPIRED_UNFILLED = never tracked (e.g. orphaned by a restart) - it has
        # no honest outcome, so it must not dilute or pad the win rate.
        resolved = [r for r in rows
                    if r["status"] not in ("ACTIVE", "OPEN", "EXPIRED_UNFILLED")]
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
