"""End-to-end engine tests over synthetic data (no network, no server)."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.backtest.replay import Backtest, bar_to_quotes
from app.config import Settings
from app.engine.session import Phase, phase_at, session_date
from app.feed.sim_feed import generate_history
from app.models import Bar, Direction, Grade, Quote, Signal, SignalStatus

ET = ZoneInfo("America/New_York")


def ts_et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=ET).timestamp()


def test_phases():
    # Mon Jul 6 2026
    assert phase_at(ts_et(2026, 7, 6, 9, 31)) == Phase.OPEN_QUIET
    assert phase_at(ts_et(2026, 7, 6, 9, 40)) == Phase.OPEN_DRIVE
    assert phase_at(ts_et(2026, 7, 6, 11, 0)) == Phase.MORNING
    assert phase_at(ts_et(2026, 7, 6, 12, 30)) == Phase.LUNCH
    assert phase_at(ts_et(2026, 7, 6, 14, 0)) == Phase.AFTERNOON
    assert phase_at(ts_et(2026, 7, 6, 15, 50)) == Phase.CLOSE
    assert phase_at(ts_et(2026, 7, 6, 17, 30)) == Phase.CLOSED
    assert phase_at(ts_et(2026, 7, 6, 20, 0)) == Phase.OVERNIGHT
    assert phase_at(ts_et(2026, 7, 4, 12, 0)) == Phase.CLOSED  # Saturday


def test_session_date_rolls_at_globex_open():
    assert session_date(ts_et(2026, 7, 6, 14, 0)) == "2026-07-06"
    assert session_date(ts_et(2026, 7, 6, 19, 0)) == "2026-07-06+"


def test_bar_to_quotes_covers_extremes():
    bar = Bar(0, 100, 110, 95, 105, 800)
    quotes = bar_to_quotes(bar)
    prices = [q.last for q in quotes]
    assert max(prices) == 110 and min(prices) == 95
    assert prices[0] == 100 and prices[-1] == 105
    assert all(0 <= q.ts < 60 for q in quotes)


def test_backtest_runs_and_resolves_signals():
    bars = generate_history(days=8, seed=42)
    assert len(bars) > 3000
    stats = Backtest().run(bars)
    # The engine must produce some calls on 8 days of varied tape...
    assert stats["signals"] > 0
    # ...and resolve nearly all of them (none stuck open forever).
    assert stats["resolved"] >= stats["signals"] - 1
    # Sanity: every resolution type is a known status.
    for s in Backtest().journal.recent(5):
        assert s["status"] in SignalStatus.__members__


def test_journal_outcome_tracking():
    from app.engine.risk import CircuitBreaker
    from app.journal.journal import Journal

    settings = Settings()
    breaker = CircuitBreaker(settings)
    journal = Journal(":memory:", settings, breaker)
    base = ts_et(2026, 7, 6, 10, 0)

    sig = Signal(direction=Direction.LONG, grade=Grade.B, score=3.5,
                 entry=25000.0, stop=24980.0, target1=25020.0, target2=25040.0,
                 contracts=1, risk_dollars=40.0, setup_type="test",
                 reasons=["test"], ts=base, expires_at=base + 90)
    journal.record(sig)
    assert journal.open_signal is not None

    # Price runs to target 1 -> win.
    journal.on_quote(Quote(ts=base + 30, last=25021.0))
    assert journal.open_signal is None
    rec = journal.recent(1)[0]
    assert rec["status"] == "TARGET1"
    assert rec["pnl_dollars"] == 40.0

    # A stop-out increments the breaker.
    sig2 = Signal(direction=Direction.SHORT, grade=Grade.B, score=3.5,
                  entry=25000.0, stop=25020.0, target1=24980.0, target2=24960.0,
                  contracts=2, risk_dollars=80.0, setup_type="test",
                  reasons=["test"], ts=base + 120, expires_at=base + 210)
    journal.record(sig2)
    journal.on_quote(Quote(ts=base + 150, last=25021.0))
    rec2 = journal.recent(1)[0]
    assert rec2["status"] == "STOPPED"
    assert rec2["pnl_dollars"] == -80.0
    assert breaker.losses_today == 1


def test_runner_logic_two_contracts():
    from app.engine.risk import CircuitBreaker
    from app.journal.journal import Journal

    settings = Settings()
    journal = Journal(":memory:", settings, CircuitBreaker(settings))
    base = ts_et(2026, 7, 6, 10, 0)
    sig = Signal(direction=Direction.LONG, grade=Grade.A, score=5.0,
                 entry=25000.0, stop=24980.0, target1=25020.0, target2=25040.0,
                 contracts=2, risk_dollars=80.0, setup_type="test",
                 reasons=["test"], ts=base, expires_at=base + 90)
    journal.record(sig)

    journal.on_quote(Quote(ts=base + 30, last=25020.5))   # T1: bank half
    assert journal.open_signal is not None                # runner still on
    journal.on_quote(Quote(ts=base + 60, last=25041.0))   # T2: runner exits
    rec = journal.recent(1)[0]
    assert rec["status"] == "TARGET2"
    # half banked 1R ($40) + runner 2R ($80) = $120
    assert rec["pnl_dollars"] == 120.0
