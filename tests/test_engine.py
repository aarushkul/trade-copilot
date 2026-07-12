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
    # 16:00-18:00 is CLOSED: the journal force-flattens open signals in this
    # window, so the engine must never treat it as tradeable in any mode.
    assert phase_at(ts_et(2026, 7, 6, 16, 0)) == Phase.CLOSED
    assert phase_at(ts_et(2026, 7, 6, 16, 30)) == Phase.CLOSED
    assert phase_at(ts_et(2026, 7, 6, 17, 30)) == Phase.CLOSED
    assert phase_at(ts_et(2026, 7, 6, 20, 0)) == Phase.OVERNIGHT
    assert phase_at(ts_et(2026, 7, 4, 12, 0)) == Phase.CLOSED  # Saturday


def test_session_date_rolls_at_globex_open():
    assert session_date(ts_et(2026, 7, 6, 14, 0)) == "2026-07-06"
    # 18:00 ET Globex open starts the *next* trading day...
    assert session_date(ts_et(2026, 7, 6, 19, 0)) == "2026-07-07"
    # ...and the key must not change at midnight (same Globex session).
    assert session_date(ts_et(2026, 7, 6, 23, 59)) == \
        session_date(ts_et(2026, 7, 7, 0, 1)) == "2026-07-07"


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
    stats = Backtest().run(bars, warmup_sessions=3)
    # The engine must produce some calls on days of varied tape...
    assert stats["signals"] > 0
    # ...and resolve nearly all of them (none stuck open forever).
    assert stats["n"] >= stats["signals"] - 1
    # Sanity: every resolution type is a known status.
    for s in Backtest().journal.recent(5):
        assert s["status"] in SignalStatus.__members__


def test_backtest_trigger_isolation():
    bars = generate_history(days=8, seed=42)
    bt = Backtest(triggers={"pullback"})
    bt.run(bars, warmup_sessions=3)
    for s in bt.signals:
        assert s.setup_type == "pullback"


def test_journal_outcome_tracking():
    from app.engine.risk import CircuitBreaker
    from app.journal.journal import Journal

    # Zero friction so the bracket math is exact; friction has its own test.
    settings = Settings(commission_per_side=0.0, slippage_ticks=0)
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

    settings = Settings(commission_per_side=0.0, slippage_ticks=0)
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


def test_friction_applied_to_journal_pnl():
    """Journal stats must be net of commissions and slippage, not gross."""
    from app.engine.risk import CircuitBreaker
    from app.journal.journal import Journal

    settings = Settings(commission_per_side=0.74, slippage_ticks=1)
    journal = Journal(":memory:", settings, CircuitBreaker(settings))
    base = ts_et(2026, 7, 6, 10, 0)

    # 1-contract winner at T1 (limit exit): 2 commissions + entry slip only.
    sig = Signal(direction=Direction.LONG, grade=Grade.B, score=3.5,
                 entry=25000.0, stop=24980.0, target1=25020.0, target2=25040.0,
                 contracts=1, risk_dollars=40.0, setup_type="test",
                 reasons=["test"], ts=base, expires_at=base + 90)
    journal.record(sig)
    journal.on_quote(Quote(ts=base + 30, last=25021.0))
    assert journal.recent(1)[0]["pnl_dollars"] == 40.0 - 2 * 0.74 - 0.50

    # 1-contract stop-out (market exit): 2 commissions + slip both ways.
    sig2 = Signal(direction=Direction.LONG, grade=Grade.B, score=3.5,
                  entry=25000.0, stop=24980.0, target1=25020.0, target2=25040.0,
                  contracts=1, risk_dollars=40.0, setup_type="test",
                  reasons=["test"], ts=base + 300, expires_at=base + 390)
    journal.record(sig2)
    journal.on_quote(Quote(ts=base + 330, last=24979.0))
    assert journal.recent(1)[0]["pnl_dollars"] == -40.0 - 2 * 0.74 - 2 * 0.50


def test_no_entries_in_post_close_window_even_with_rth_off():
    """Regression: with rth_only=False and cooldown=0, the engine fired every
    15s between 16:00-18:00 and the journal flattened each signal 1s later
    (fire/flatten loop). CLOSED must block entries regardless of settings."""
    from app.engine.engine import SignalEngine

    settings = Settings(rth_only=False, signal_cooldown_sec=0,
                        circuit_breaker_enabled=False)
    engine = SignalEngine(settings)
    fired = []
    engine.on_signal = fired.append

    # Warm the engine with an RTH afternoon, then cross into 16:00-18:00.
    bars = generate_history(days=3, seed=3,
                            end_ts=ts_et(2026, 7, 6, 15, 55))
    engine.seed_history(bars)
    ts = ts_et(2026, 7, 6, 16, 0)
    price = bars[-1].close
    for i in range(240):  # one hour of quotes at 15s cadence
        engine.on_quote(Quote(ts=ts + i * 15, last=price + (i % 7) * 2))
    assert fired == []
    assert "closed" in engine._standing_aside.lower()


def test_displacement_note_is_advisory_only():
    """A huge-range, high-volume 1m bar must set the dashboard note - and
    only the note. Chasing such bars as a trigger measured PF 0.47 over 25
    real sessions (2026-07-09), so the note can never fire a signal, and it
    ages out on tape time so live and replay behave identically."""
    from app.engine.engine import SignalEngine

    eng = SignalEngine(Settings())
    fired = []
    eng.on_signal = fired.append
    t0 = ts_et(2026, 7, 6, 10, 0)  # Monday, mid-morning RTH
    warm = [Bar(t0 + i * 60, 29800.0, 29802.0, 29798.0, 29800.0, 1000)
            for i in range(40)]
    eng.seed_history(warm)
    states = []
    eng.on_state = states.append

    # 46-pt down bar on 5x average volume, then a quote that rolls the minute.
    big_ts = warm[-1].ts + 60
    big = Bar(big_ts, 29800.0, 29801.0, 29755.0, 29756.0, 5000)
    for q in bar_to_quotes(big):
        eng.on_quote(q)
    assert states and states[0]["displacement"] is None  # not before it closes
    eng.on_quote(Quote(ts=big_ts + 61, last=29756.0, bid=29755.75,
                       ask=29756.25, last_size=1))
    note = states[-1]["displacement"]
    assert note is not None
    assert note["direction"] == "SELL"
    assert note["points"] >= 40
    assert note["rvol"] >= 2.0
    assert fired == []  # advisory only, never a signal by itself

    # Note expires after DISPLACEMENT_NOTE_TTL_SEC of *tape* time.
    eng.on_quote(Quote(ts=big_ts + 61 + 700, last=29756.0, bid=29755.75,
                       ask=29756.25, last_size=1))
    assert states[-1]["displacement"] is None


def test_selectivity_window_defaults():
    """2026-07-12 selectivity mode: the tod study (1,680 sessions) measured
    09:30-10:00 as the worst bucket both directions and 15:00+ as the worst
    for longs, so the default windows now block them."""
    s = Settings()
    assert s.no_open_minutes == 30 and s.last_entry_minutes == 60
    assert phase_at(ts_et(2026, 7, 6, 9, 45), 30, 60) == Phase.OPEN_QUIET
    assert phase_at(ts_et(2026, 7, 6, 10, 5), 30, 60) == Phase.OPEN_DRIVE
    assert phase_at(ts_et(2026, 7, 6, 14, 55), 30, 60) == Phase.AFTERNOON
    assert phase_at(ts_et(2026, 7, 6, 15, 10), 30, 60) == Phase.CLOSE


def test_daily_signal_cap_blocks_third_signal():
    from app.engine.engine import SignalEngine

    eng = SignalEngine(Settings(daily_signal_cap=2))
    eng.on_signal = lambda s: None
    warm = generate_history(days=3, seed=5, end_ts=ts_et(2026, 7, 6, 10, 30))
    eng.seed_history(warm)
    day = "2026-07-06"
    eng._signals_day = (day, 2)
    states = []
    eng.on_state = states.append
    t = ts_et(2026, 7, 6, 10, 31)
    eng.on_quote(Quote(ts=t, last=warm[-1].close))
    eng.on_quote(Quote(ts=t + 16, last=warm[-1].close))   # roll the 15s bar
    assert "daily cap" in eng._standing_aside
    assert states[-1]["signals_today"] == 2


def test_a_grade_only_demotes_b_grade_confluence():
    from types import SimpleNamespace

    from app.engine.engine import SignalEngine
    from app.models import Vote

    ctx = SimpleNamespace(structure=None, phase=Phase.MORNING,
                          rvol_1m=1.0, trend_5m=lambda: Direction.LONG)
    votes = [Vote(Direction.LONG, 2.5, "pullback at ema21", "pullback"),
             Vote(Direction.LONG, 2.0, "vwap side", "vwap",
                  is_trend_aligned=True)]
    # score 4.5 >= fire_b, < fire_a(4.75-ish w/ defaults 4.5): use defaults
    s = Settings(score_fire_b=4.0, score_fire_a=5.0)
    eng = SignalEngine(s)
    assert eng._score(ctx, votes) is None          # B-grade suppressed

    s2 = Settings(score_fire_b=4.0, score_fire_a=5.0, a_grade_only=False)
    eng2 = SignalEngine(s2)
    got = eng2._score(ctx, votes)
    assert got is not None and got[1] == Grade.B   # context becomes a call only if enabled


def test_levels_break_note_is_advisory_context():
    """The one 7-year-persistent research pattern (PF 2.17, t 2.9, n=68 —
    UNVALIDATED) surfaces as a banner and never as a signal."""
    from app.engine.engine import SignalEngine

    eng = SignalEngine(Settings())
    fired = []
    eng.on_signal = fired.append
    t0 = ts_et(2026, 7, 6, 10, 30)   # Monday, past the 30-min open block
    warm = [Bar(t0 + i * 60, 29800.0, 29802.0, 29798.0, 29800.0, 1000)
            for i in range(90)]
    eng.seed_history(warm)
    eng.levels.levels.prior_day_high = 29830.0     # ~30 pts above (>= 5x atr_1m)
    states = []
    eng.on_state = states.append

    brk_ts = warm[-1].ts + 60
    brk = Bar(brk_ts, 29800.0, 29841.0, 29799.0, 29836.0, 1200)
    for q in bar_to_quotes(brk):
        eng.on_quote(q)
    eng.on_quote(Quote(ts=brk_ts + 61, last=29836.0, bid=29835.75,
                       ask=29836.25, last_size=1))
    note = states[-1]["levels_break"]
    assert note is not None
    assert note["level"] == "PDH" and note["direction"] == "BUY"
    assert note["through_pts"] >= 1.0
    assert fired == []                              # context, never a call

    # ages out on tape time, like the displacement note
    eng.on_quote(Quote(ts=brk_ts + 61 + 1000, last=29836.0, bid=29835.75,
                       ask=29836.25, last_size=1))
    assert states[-1]["levels_break"] is None
