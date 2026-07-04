import math

from app.indicators.core import (
    VwapState,
    atr,
    ema,
    is_bearish_pin,
    is_bullish_engulfing,
    is_bullish_pin,
    relative_volume,
    rsi,
)
from app.models import Bar


def mk_bars(closes, vol=100):
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        bars.append(Bar(i * 60.0, o, max(o, c) + 1, min(o, c) - 1, c, vol))
    return bars


def test_ema_converges_to_constant():
    assert math.isclose(ema([100.0] * 50, 9), 100.0)


def test_ema_needs_enough_data():
    assert ema([1.0, 2.0], 9) is None


def test_rsi_bounds_and_direction():
    up = rsi([float(i) for i in range(1, 40)], 14)
    down = rsi([float(40 - i) for i in range(1, 40)], 14)
    assert up is not None and up > 95
    assert down is not None and down < 5


def test_atr_positive():
    bars = mk_bars([100 + (i % 5) for i in range(30)])
    a = atr(bars, 14)
    assert a is not None and a > 0


def test_vwap_tracks_volume_weighting():
    v = VwapState()
    v.add_bar(Bar(0, 100, 100, 100, 100, 100))     # typical 100
    v.add_bar(Bar(60, 200, 200, 200, 200, 300))    # typical 200, 3x weight
    assert math.isclose(v.vwap, (100 * 100 + 200 * 300) / 400)
    assert v.sigma > 0


def test_relative_volume():
    bars = mk_bars([100] * 21)
    bars[-1].volume = 300
    assert math.isclose(relative_volume(bars, 20), 3.0)


def test_patterns():
    prev = Bar(0, 100, 101, 98, 98.5)             # red
    cur = Bar(60, 98.4, 102, 98.2, 101.8)         # big green engulfing
    assert is_bullish_engulfing(prev, cur)

    hammer = Bar(0, 100, 100.4, 96, 100.1)        # long lower wick
    assert is_bullish_pin(hammer)
    assert not is_bearish_pin(hammer)
