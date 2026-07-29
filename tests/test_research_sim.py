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


# ------------------------------------------------------- sim-1.1 (trail)

def _trail_args(bars):
    return (np.array([b.open for b in bars]), np.array([b.high for b in bars]),
            np.array([b.low for b in bars]), np.array([b.close for b in bars]),
            np.array([b.ts for b in bars]),
            np.array([sim._minute_et(b.ts) for b in bars]))


def test_trail_ratchets_and_exits_at_trail_level():
    bars = mk_bars([
        (100, 101, 99.5, 100),                 # signal bar
        (100, 104, 99, 103),                   # entry 100.25; ext becomes 104
        (103, 103.5, 100.5, 101),              # eff = 104-3 = 101 -> TRAIL
    ])
    tr, j = sim.resolve_trail(*_trail_args(bars), 0, +1,
                              stop_pts=5.0, trail_pts=3.0, session="s")
    assert (tr.exit_reason, j) == ("TRAIL", 2)
    assert tr.entry_px == 100.25
    assert tr.exit_px == pytest.approx(100.75)          # 101 - 0.25 slip
    assert tr.pnl_usd == pytest.approx(0.5 * POINT_VALUE - 1.48)


def test_trail_gap_through_fills_at_open():
    bars = mk_bars([
        (100, 101, 99.5, 100),
        (100, 104, 99, 103),
        (100, 100.5, 98, 99),                  # opens below eff 101
    ])
    tr, _ = sim.resolve_trail(*_trail_args(bars), 0, +1,
                              stop_pts=5.0, trail_pts=3.0, session="s")
    assert tr.exit_reason == "TRAIL"
    assert tr.exit_px == pytest.approx(99.75)           # open 100 - slip


def test_trail_initial_stop_on_entry_bar_is_STOP():
    bars = mk_bars([
        (100, 101, 99.5, 100),
        (100, 101, 95.0, 96),                  # low 95.0 <= stop 95.25
    ])
    tr, _ = sim.resolve_trail(*_trail_args(bars), 0, +1,
                              stop_pts=5.0, trail_pts=3.0, session="s")
    assert tr.exit_reason == "STOP"
    assert tr.exit_px == pytest.approx(95.0)            # 95.25 - slip


def test_trail_flat_at_1559():
    start = datetime(2024, 3, 5, 15, 56, tzinfo=ET)
    bars = mk_bars([
        (100, 101, 99.5, 100),                 # 15:56 signal
        (100, 101, 99.5, 100.5),               # 15:57 entry
        (100.5, 102, 99.6, 101),               # 15:58
        (107, 107.5, 106, 107),                # 15:59 -> FLAT at open
    ], start=start)
    tr, j = sim.resolve_trail(*_trail_args(bars), 0, +1,
                              stop_pts=5.0, trail_pts=30.0, session="s")
    assert (tr.exit_reason, j) == ("FLAT", 3)
    assert tr.exit_px == pytest.approx(106.75)
    assert tr.pnl_usd == pytest.approx(6.5 * POINT_VALUE - 1.48)


def test_trail_short_mirror():
    bars = mk_bars([
        (100, 100.5, 99.5, 100),
        (100, 100.5, 96, 97),                  # entry 99.75; ext(low) 96
        (98, 99.5, 97.5, 99),                  # eff = 96+3 = 99 -> TRAIL
    ])
    tr, _ = sim.resolve_trail(*_trail_args(bars), 0, -1,
                              stop_pts=5.0, trail_pts=3.0, session="s")
    assert tr.exit_reason == "TRAIL"
    assert tr.exit_px == pytest.approx(99.25)           # max(98,99) + slip
    assert tr.pnl_usd == pytest.approx(0.5 * POINT_VALUE - 1.48)


def test_run_rule_trail_busy_consumes_second_signal():
    bars = mk_bars([
        (100, 101, 99.5, 100),                 # signal 1
        (100, 104, 99, 103),                   # entry
        (103, 103.5, 100.5, 101),              # TRAIL exit here (busy till 2)
        (101, 101.5, 100.5, 101),              # signal 2 at i=3 -> allowed
        (101, 101.2, 96, 97),
    ])
    long_m = np.zeros(5, bool); long_m[[0, 1, 3]] = True   # i=1 busy-skipped
    short_m = np.zeros(5, bool)
    stops = np.full(5, 5.0); trails = np.full(5, 3.0)
    trades = sim.run_rule_trail({"s": bars}, {"s": (long_m, short_m)},
                                {"s": stops}, {"s": trails})
    assert len(trades) == 2
    assert trades[0].exit_reason == "TRAIL"
    assert trades[1].entry_i == 4
