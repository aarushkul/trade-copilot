"""Golden deterministic tests for the sim-1 fill/cost model.

Every value here is hand-derived. If sim.py changes behavior, these numbers
changing means SIM_VERSION must bump and prior ledger results are void.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from app.config import POINT_VALUE, TICK_SIZE
from app.models import Bar
from app.research import sim

ET = ZoneInfo("America/New_York")
T0 = datetime(2024, 3, 5, 10, 0, tzinfo=ET)  # ordinary Tuesday, RTH


def mk_bars(rows, start=T0):
    """rows = [(open, high, low, close)] one per minute."""
    return [Bar((start + timedelta(minutes=i)).timestamp(), o, h, l, c, 100)
            for i, (o, h, l, c) in enumerate(rows)]


def test_long_target_needs_trade_through_not_touch():
    bars = mk_bars([
        (20000, 20001, 19999, 20000),          # signal bar
        (20000, 20005, 19998, 20004),          # entry at open 20000 + 0.25 slip
        (20004, 20020.25, 20003, 20010),       # touches target exactly -> NO fill
        (20010, 20020.50, 20009, 20015),       # trades through -> fill AT target
    ])
    tr = sim.resolve_bracket(bars, 0, +1, stop_pts=10.0, target_pts=20.0,
                             horizon_min=None, session="2024-03-05")
    assert tr.exit_reason == "TARGET"
    assert tr.entry_px == 20000.25
    assert tr.exit_px == 20020.25
    # 20.00 pts * $2 - 2*$0.74 = $38.52 ; r = 38.52 / (10*2) = 1.926
    assert tr.pnl_usd == pytest.approx(38.52)
    assert tr.r == pytest.approx(1.926)


def test_stop_pays_slippage():
    bars = mk_bars([
        (20000, 20001, 19999, 20000),
        (20000, 20002, 19998, 19999),          # entry 20000.25, stop 19990.25
        (19999, 20000, 19990.25, 19991),       # touch stop -> market out with slip
    ])
    tr = sim.resolve_bracket(bars, 0, +1, 10.0, 20.0, None, "2024-03-05")
    assert tr.exit_reason == "STOP"
    assert tr.exit_px == 19990.00               # stop - 1 tick slip
    # (19990.00 - 20000.25) * $2 - $1.48 = -$21.98
    assert tr.pnl_usd == pytest.approx(-21.98)


def test_both_in_one_bar_scores_stop():
    bars = mk_bars([
        (20000, 20001, 19999, 20000),
        (20000, 20002, 19999, 20001),          # entry 20000.25
        (20001, 20025, 19989, 20020),          # stop AND target inside -> STOP
    ])
    tr = sim.resolve_bracket(bars, 0, +1, 10.0, 20.0, None, "2024-03-05")
    assert tr.exit_reason == "STOP"


def test_short_side_mirrors():
    bars = mk_bars([
        (20000, 20001, 19999, 20000),
        (20000, 20001, 19995, 19996),          # short entry 20000 - 0.25 slip
        (19996, 19997, 19979.50, 19980),       # target 19979.75 needs low <= 19979.50
    ])
    tr = sim.resolve_bracket(bars, 0, -1, 10.0, 20.0, None, "2024-03-05")
    assert tr.exit_reason == "TARGET"
    assert tr.entry_px == 19999.75
    assert tr.exit_px == 19979.75
    assert tr.pnl_usd == pytest.approx(38.52)


def test_horizon_exits_at_bar_open_with_slip():
    rows = [(20000, 20001, 19999, 20000)] * 8
    bars = mk_bars(rows)
    tr = sim.resolve_bracket(bars, 0, +1, 50.0, 100.0, horizon_min=5,
                             session="2024-03-05")
    assert tr.exit_reason == "HORIZON"
    assert tr.exit_ts == bars[6].ts             # entry bar 1 + 5 bars
    assert tr.exit_px == 20000 - 0.25


def test_force_flat_at_1559():
    start = datetime(2024, 3, 5, 15, 57, tzinfo=ET)
    bars = mk_bars([(20000, 20001, 19999, 20000)] * 4, start=start)  # 15:57..16:00
    tr = sim.resolve_bracket(bars, 0, +1, 50.0, 100.0, None, "2024-03-05")
    assert tr.exit_reason == "FLAT"
    assert datetime.fromtimestamp(tr.exit_ts, tz=ET).minute == 59


def test_no_entry_at_or_after_flat_minute():
    start = datetime(2024, 3, 5, 15, 58, tzinfo=ET)
    bars = mk_bars([(20000, 20001, 19999, 20000)] * 3, start=start)
    assert sim.resolve_bracket(bars, 0, +1, 10.0, 20.0, None) is None


def test_cost_arithmetic_matches_journal_semantics():
    """Journal (app/journal/journal.py:198-212) charges 2*commission*contracts
    plus slippage ticks on each market fill; sim-1 bakes slippage into fill
    prices instead. For a 1-contract stop-out both must agree to the cent."""
    bars = mk_bars([
        (20000, 20001, 19999, 20000),
        (20000, 20002, 19998, 19999),
        (19999, 20000, 19990.25, 19991),
    ])
    tr = sim.resolve_bracket(bars, 0, +1, 10.0, 20.0, None)
    entry_ref, stop_ref = 20000.0, 19990.25
    tick_value = TICK_SIZE * POINT_VALUE
    journal_style = ((stop_ref - entry_ref) * POINT_VALUE
                     - 2 * sim.COMMISSION_PER_SIDE          # commissions
                     - 2 * sim.SLIPPAGE_TICKS * tick_value)  # entry + stop fills
    assert tr.pnl_usd == pytest.approx(journal_style)


def test_firewall_blocks_forward_columns():
    with pytest.raises(ValueError):
        sim.assert_causal(["vwap_dist_sigma", "fwd_net_r_60m"])
    sim.assert_causal(["vwap_dist_sigma", "rsi_1m"])  # fine


def test_run_rule_one_position_at_a_time():
    rows = [(20000, 20001, 19999, 20000)] * 40
    bars = mk_bars(rows)
    n = len(bars)
    long_m = np.zeros(n, dtype=bool)
    long_m[[2, 3, 4]] = True                    # overlapping signals
    masks = {"2024-03-05": (long_m, np.zeros(n, dtype=bool))}
    stops = {"2024-03-05": np.full(n, 10.0)}
    trades = sim.run_rule({"2024-03-05": bars}, masks, stops,
                          target_r=2.0, horizon_min=5)
    assert len(trades) == 1                     # busy until first trade exits
