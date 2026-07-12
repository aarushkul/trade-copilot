"""Tests for the Powell-strategy backtester (app/backtest/powell.py).

One hand-built 1m tape drives most tests: flat warmup with an old liquidity
pool at 19970, a confirmed swing low at 19992 and swing high at 20010, then a
sweep spike to 20014 that reclaims, a displacement MSS through 19992, and a
retrace. Every price is chosen so swing confirmation, ATR depth, displacement
and fill mechanics are deterministic.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.backtest.powell import (
    MarketState,
    PowellBacktest,
    PowellParams,
    _entries_allowed,
)
from app.models import Bar

ET = ZoneInfo("America/New_York")


def _ts(i: int, base: str = "2026-06-15 09:20") -> float:
    dt = datetime.strptime(base, "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    return (dt + timedelta(minutes=i)).timestamp()


def mk(i: int, o: float, h: float, lo: float, c: float,
       base: str = "2026-06-15 09:20") -> Bar:
    return Bar(_ts(i, base), o, h, lo, c, 500)


def build_short_setup(base: str = "2026-06-15 09:20") -> list[Bar]:
    """Bars 0..45: warmup, old pool, swings, sweep, MSS. Retrace appended by
    each test so fill/miss/stop variants share the same setup."""
    bars: list[Bar] = []
    for i in range(10):                       # flat
        bars.append(mk(i, 20000, 20001, 19999, 20000, base))
    dip = [(19998, 20000, 19996, 19997), (19992, 19998, 19990, 19991),
           (19982, 19992, 19980, 19981), (19972, 19982, 19970, 19971),
           (19982, 19984, 19981, 19983), (19992, 19993, 19991, 19992),
           (19998, 19999, 19997, 19998)]      # old pool: swing low 19970 @ 13
    for j, (o, h, lo, c) in enumerate(dip):
        bars.append(mk(10 + j, o, h, lo, c, base))
    for i in range(17, 30):                   # flat again
        bars.append(mk(i, 20000, 20001, 19999, 20000, base))
    desc = [(20000, 20000, 19997, 19998), (19998, 19998, 19995, 19996),
            (19996, 19996, 19993, 19994), (19994, 19995, 19992, 19993),
            (19993, 19996, 19993, 19996), (19996, 19998, 19995, 19998),
            (19998, 20000, 19997, 20000)]     # swing low 19992 @ 33
    for j, (o, h, lo, c) in enumerate(desc):
        bars.append(mk(30 + j, o, h, lo, c, base))
    rise = [(20000, 20005, 19999, 20004), (20004, 20009, 20003, 20008),
            (20008, 20010, 20007, 20009),     # swing high 20010 @ 39
            (20009, 20008, 20005, 20007), (20007, 20006, 20004, 20005),
            (20005, 20007, 20004, 20006)]
    for j, (o, h, lo, c) in enumerate(rise):
        bars.append(mk(37 + j, o, h, lo, c, base))
    # 43: sweep — wick through 20010 to 20014, close back below (rejection)
    bars.append(mk(43, 20006, 20014, 20004, 20007, base))
    # 44: drifts down, leaves the FVG gap (this bar's neighbours don't overlap)
    bars.append(mk(44, 20006, 20006, 19994, 19995, base))
    # 45: displacement MSS — full body through the 19992 swing low
    bars.append(mk(45, 19994, 19994.5, 19986, 19987, base))
    return bars


def run_setup(extra: list[Bar], base: str = "2026-06-15 09:20",
              **param_overrides) -> PowellBacktest:
    params = PowellParams(**({"entry_mode": "fvg", "target_mode": "liq",
                              "time_filter": "rth"} | param_overrides))
    bt = PowellBacktest(params)
    bt.run(build_short_setup(base) + extra, warmup=30)
    return bt


def test_sweep_and_mss_arm_one_short_signal():
    bt = run_setup([])
    assert bt.funnel["placed"] == 1
    assert bt.pending and bt.pending[0][0].direction.value == "SHORT"
    order = bt.pending[0][0]
    assert order.stop == 20014.5          # sweep extreme 20014 + 2 ticks
    assert order.target == 19970.5        # old pool 19970 front-run 2 ticks


def test_fvg_entry_is_gap_midpoint():
    bt = run_setup([])
    # gap between bar43.low (20004) and bar45.high (19994.5) -> CE 19999.25
    assert bt.pending[0][0].entry == 19999.25


def test_half_entry_is_leg_midpoint():
    bt = run_setup([], entry_mode="half")
    # leg = sweep extreme 20014 -> MSS low 19986; midpoint 20000
    assert bt.pending[0][0].entry == 20000.0


def test_mkt_entry_opens_immediately_with_slippage():
    bt = run_setup([], entry_mode="mkt", target_mode="r", target_r=2.0)
    assert bt.funnel["filled"] == 1
    assert bt.open_trades or bt.trades    # opened on the MSS bar itself
    t = (bt.open_trades[0][0] if bt.open_trades else bt.trades[0])
    assert t.entry == 19987 - 0.25        # MSS close, sold one slippage tick worse


def test_retrace_fill_then_target_win_with_costs():
    extra = [mk(46, 19990, 20001, 19989, 19998),   # retrace fills the limit
             mk(47, 19989, 19990, 19969, 19972)]   # run through the pool target
    bt = run_setup(extra, entry_mode="half")
    assert [t.status for t in bt.trades] == ["WIN"]
    t = bt.trades[0]
    assert t.entry == 20000.0 and t.exit_price == 19970.5
    # (29.5 pts * $2) - 2 * $0.74 commission; target is a limit -> no slippage
    assert t.pnl_dollars == 57.52
    assert abs(t.pnl_r - 29.5 / 14.5) < 1e-3   # stored rounded to 3 dp


def test_limit_requires_trade_through_not_touch():
    extra = [mk(46, 19990, 19999.25, 19989, 19992)]  # touches CE exactly
    bt = run_setup(extra)
    assert bt.funnel["filled"] == 0
    assert bt.pending                    # order still working


def test_target_before_fill_counts_missed_winner():
    extra = [mk(46, 19985, 19986, 19969, 19971)]   # collapses without retrace
    bt = run_setup(extra)
    assert bt.funnel["filled"] == 0
    assert [t.status for t in bt.trades] == ["CANCELLED_TGT_FIRST"]


def test_stop_out_pays_slippage():
    extra = [mk(46, 19990, 20001, 19989, 19998),   # fill at 20000 (half mode)
             mk(47, 20001, 20016, 20000, 20014)]   # rallies through the stop
    bt = run_setup(extra, entry_mode="half")
    assert [t.status for t in bt.trades] == ["LOSS"]
    t = bt.trades[0]
    assert t.exit_price == 20014.75       # stop 20014.5 + 1 tick slip (short)
    assert t.pnl_dollars == -30.98        # -14.75 pts * $2 - $1.48 commission


def test_breakout_that_holds_is_not_a_sweep():
    """Clean push through the pool that keeps closing above must retire the
    pool, not arm a reversal — the model trades stop-runs, not breakouts."""
    bars = build_short_setup()[:43]
    for j, (o, h, lo, c) in enumerate(
            [(20006, 20014, 20005, 20013), (20013, 20016, 20012, 20015),
             (20015, 20018, 20014, 20017), (20017, 20017, 20008, 20009),
             (20009, 20010, 19985, 19986)]):     # late collapse
        bars.append(mk(43 + j, o, h, lo, c))
    bt = PowellBacktest(PowellParams(entry_mode="half"))
    bt.run(bars, warmup=30)
    assert bt.funnel["sweeps"] == 0 and bt.funnel["placed"] == 0


def test_no_entries_outside_rth():
    bt = run_setup([], base="2026-06-15 03:20")   # setup completes ~04:05 ET
    assert bt.funnel["placed"] == 0


def test_open_position_force_flat_before_close():
    # setup completes 15:25 ET; fill, then drift so 15:59 forces the exit
    base = "2026-06-15 14:40"
    extra = [mk(46, 19990, 20001, 19989, 19998, base)]
    extra += [mk(47 + j, 19998, 20003, 19993, 19998, base) for j in range(40)]
    bt = run_setup(extra, base=base, entry_mode="half")
    assert [t.status for t in bt.trades] == ["FLAT"]
    assert _et_hour_min(bt.trades[0].exit_ts) == (15, 59)


def _et_hour_min(ts: float) -> tuple[int, int]:
    dt = datetime.fromtimestamp(ts, tz=ET)
    return dt.hour, dt.minute


def test_entries_allowed_windows():
    def at(hhmm: str) -> float:
        return _ts(0, f"2026-06-15 {hhmm}")
    assert _entries_allowed(at("10:00"), "rth")
    assert not _entries_allowed(at("09:15"), "rth")
    assert not _entries_allowed(at("15:50"), "rth")
    assert _entries_allowed(at("11:00"), "nyam")
    assert not _entries_allowed(at("13:00"), "nyam")
    assert _entries_allowed(at("03:00"), "all")
    assert not _entries_allowed(at("16:30"), "all")   # CLOSED phase
    assert not _entries_allowed(_ts(0, "2026-06-13 10:00"), "all")  # Saturday


def test_5m_swings_confirm_causally():
    """A 5m pivot is only visible after two later 5m bars have closed."""
    st = MarketState(PowellParams(pool_tf="5m"))
    for i in range(30):
        if 10 <= i < 15:                       # slot 2 spikes
            st.push(mk(i, 20000, 20020, 19999, 20000))
        else:
            st.push(mk(i, 20000, 20001, 19999, 20000))
        if i < 25:
            assert not st.swing_highs5         # not confirmable yet
    confirm_idx, price = st.swing_highs5[0]
    assert price == 20020 and confirm_idx == 25
