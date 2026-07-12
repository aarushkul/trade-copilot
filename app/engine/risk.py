"""Risk module: dynamic per-trade risk, position sizing, daily circuit breaker."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import POINT_VALUE, TICK_SIZE, Settings
from app.models import Direction, Grade


def round_tick(price: float) -> float:
    """Snap a price to the instrument's tick grid."""
    return round(round(price / TICK_SIZE) * TICK_SIZE, 2)


@dataclass
class TradePlan:
    entry: float
    stop: float
    target1: float
    target2: float
    contracts: int
    risk_dollars: float
    stop_points: float


@dataclass
class RiskDecision:
    plan: Optional[TradePlan]
    rejected_reason: Optional[str] = None


def build_trade_plan(direction: Direction, grade: Grade, entry: float,
                     stop_points: float, settings: Settings) -> RiskDecision:
    """Convert an entry + stop distance into a sized plan, or reject it."""
    budget = settings.risk_a_grade if grade == Grade.A else settings.risk_b_grade
    risk_per_contract = stop_points * POINT_VALUE
    if risk_per_contract <= 0:
        return RiskDecision(None, "invalid stop distance")

    contracts = int(budget // risk_per_contract)
    contracts = min(contracts, settings.max_contracts)
    if contracts < 1:
        return RiskDecision(
            None,
            f"stop too wide: {stop_points:.1f} pts is "
            f"${risk_per_contract:.0f}/contract vs ${budget:.0f} budget")

    risk_dollars = contracts * risk_per_contract
    sign = 1 if direction == Direction.LONG else -1
    entry = round_tick(entry)
    stop = round_tick(entry - sign * stop_points)
    target1 = round_tick(entry + sign * stop_points)      # 1R
    target2 = round_tick(entry + sign * stop_points * settings.target2_r)
    return RiskDecision(TradePlan(
        entry=entry, stop=stop, target1=target1, target2=target2,
        contracts=contracts, risk_dollars=round(risk_dollars, 2),
        stop_points=round(stop_points, 2)))


class CircuitBreaker:
    """Locks the engine to STAND ASIDE after N stopped-out signals in a day."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._day: Optional[str] = None
        self._losses = 0

    def on_new_day(self, day: str) -> None:
        if day != self._day:
            self._day = day
            self._losses = 0

    def record_stop_out(self, day: str) -> None:
        self.on_new_day(day)
        self._losses += 1

    def seed(self, day: str, losses: int) -> None:
        """Restore today's loss count (e.g. from the journal after a restart),
        so restarting the app cannot bypass the lockout."""
        self.on_new_day(day)
        self._losses = max(self._losses, losses)

    @property
    def losses_today(self) -> int:
        return self._losses

    def is_tripped(self, day: str) -> bool:
        self.on_new_day(day)
        return (self.settings.circuit_breaker_enabled
                and self._losses >= self.settings.circuit_breaker_losses)
