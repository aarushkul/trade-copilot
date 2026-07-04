"""Core data types shared across feed, engine, journal and server."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


@dataclass
class Quote:
    """A tick-level update from the data feed."""

    ts: float                 # epoch seconds
    last: float
    bid: float = 0.0
    ask: float = 0.0
    last_size: int = 0
    day_volume: int = 0       # cumulative session volume if the feed provides it


@dataclass
class Bar:
    ts: float                 # bar open time, epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def update(self, price: float, size: int = 0) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += size

    def to_dict(self) -> dict:
        return {
            "time": int(self.ts),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Grade(str, Enum):
    A = "A"
    B = "B"


class SignalStatus(str, Enum):
    ACTIVE = "ACTIVE"          # fired, entry window open
    EXPIRED_UNFILLED = "EXPIRED_UNFILLED"  # entry window lapsed before tracking began
    OPEN = "OPEN"              # tracking hypothetical position
    TARGET1 = "TARGET1"        # hit first target (win)
    TARGET2 = "TARGET2"        # ran to second target (bigger win)
    STOPPED = "STOPPED"        # hit stop (loss)
    FLAT_EXIT = "FLAT_EXIT"    # timed out / session end, closed at market


@dataclass
class Signal:
    direction: Direction
    grade: Grade
    score: float
    entry: float
    stop: float
    target1: float
    target2: float
    contracts: int
    risk_dollars: float
    setup_type: str
    reasons: list[str]
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    expires_at: float = 0.0
    status: SignalStatus = SignalStatus.ACTIVE
    resolved_ts: Optional[float] = None
    exit_price: Optional[float] = None
    pnl_dollars: Optional[float] = None
    pnl_r: Optional[float] = None
    mfe_points: float = 0.0    # max favourable excursion while open
    mae_points: float = 0.0    # max adverse excursion while open

    @property
    def stop_points(self) -> float:
        return abs(self.entry - self.stop)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "direction": self.direction.value,
            "grade": self.grade.value,
            "score": round(self.score, 2),
            "entry": self.entry,
            "stop": self.stop,
            "target1": self.target1,
            "target2": self.target2,
            "contracts": self.contracts,
            "risk_dollars": self.risk_dollars,
            "setup_type": self.setup_type,
            "reasons": self.reasons,
            "expires_at": self.expires_at,
            "status": self.status.value,
            "resolved_ts": self.resolved_ts,
            "exit_price": self.exit_price,
            "pnl_dollars": self.pnl_dollars,
            "pnl_r": self.pnl_r,
        }


@dataclass
class Vote:
    """A single setup module's opinion about the market right now."""

    direction: Direction
    weight: float
    reason: str
    tag: str                   # setup family, e.g. "orb", "vwap", "trend"
    is_volume_confirmed: bool = False
    is_trend_aligned: bool = False
