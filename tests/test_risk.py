from app.config import Settings
from app.engine.risk import CircuitBreaker, build_trade_plan
from app.models import Direction, Grade


def settings():
    return Settings(risk_a_grade=150, risk_b_grade=100, max_contracts=2,
                    circuit_breaker_losses=2)


def test_b_grade_sizing_two_contracts():
    # 20 pt stop = $40/contract -> $100 budget fits 2 contracts.
    d = build_trade_plan(Direction.LONG, Grade.B, 25000.0, 20.0, settings())
    assert d.plan is not None
    assert d.plan.contracts == 2
    assert d.plan.risk_dollars == 80.0  # 2 contracts x 20 pts x $2/pt
    assert d.plan.stop == 24980.0
    assert d.plan.target1 == 25020.0
    assert d.plan.target2 == 25040.0


def test_wide_stop_one_contract():
    # 60 pt stop = $120/contract -> only 1 fits in $150 A budget.
    d = build_trade_plan(Direction.SHORT, Grade.A, 25000.0, 60.0, settings())
    assert d.plan is not None
    assert d.plan.contracts == 1
    assert d.plan.stop == 25060.0
    assert d.plan.target1 == 24940.0


def test_stop_too_wide_rejected():
    # 80 pt stop = $160/contract > $100 B budget -> reject.
    d = build_trade_plan(Direction.LONG, Grade.B, 25000.0, 80.0, settings())
    assert d.plan is None
    assert "stop too wide" in d.rejected_reason


def test_max_contracts_cap():
    # 5 pt stop = $10/contract -> budget fits 10, cap at 2.
    d = build_trade_plan(Direction.LONG, Grade.B, 25000.0, 5.0, settings())
    assert d.plan.contracts == 2


def test_circuit_breaker():
    br = CircuitBreaker(settings())
    day = "2026-07-06"
    assert not br.is_tripped(day)
    br.record_stop_out(day)
    assert not br.is_tripped(day)
    br.record_stop_out(day)
    assert br.is_tripped(day)
    # New day resets.
    assert not br.is_tripped("2026-07-07")
    assert br.losses_today == 0
