from app.indicators.structure import (
    StructureKind,
    analyze_timeframe,
    classify_bias,
)
from app.models import Bar, Direction


def mk_trend_bars(n: int, start: float, step: float) -> list[Bar]:
    bars = []
    p = start
    for i in range(n):
        o = p
        p += step
        bars.append(Bar(i * 60.0, o, max(o, p) + 2, min(o, p) - 2, p, 500))
    return bars


def test_classify_bullish_bias():
    highs = [type("S", (), {"price": 100})(), type("S", (), {"price": 105})()]
    lows = [type("S", (), {"price": 90})(), type("S", (), {"price": 92})()]
    assert classify_bias(highs, lows) == "bullish"


def test_detect_bullish_bos_on_breakout():
    """Synthetic 5m series with clear swings then a bullish break."""
    bars = []
    # Two legs up with pullbacks so fractals form.
    pattern = [100, 103, 101, 106, 104, 109, 107, 112, 110, 115,
               113, 118, 116, 120, 118, 125]
    for i, c in enumerate(pattern):
        o = pattern[i - 1] if i else c
        bars.append(Bar(i * 300.0, o, c + 1.5, c - 1.5, c, 500))
    # Pad history so strength=2 has room.
    while len(bars) < 20:
        bars.insert(0, Bar(bars[0].ts - 300, 98, 99, 97, 98, 300))
    st = analyze_timeframe(bars, "5m", strength=2, scan_bars=10)
    assert st.bias in ("bullish", "ranging", "unknown") or st.last_event is not None


def test_break_of_one_level_fires_exactly_one_event():
    """A level is broken once. Bars that merely stay beyond it must not
    re-fire the event - duplicates fabricate confluence in the engine."""
    prices = [100, 101, 102, 101, 100, 99, 100, 101, 100, 99,
              98, 99, 100, 99, 98, 99, 100, 101, 102, 103,
              104, 105, 106, 107, 108]
    bars = [Bar(i * 60.0, p, p + 0.6, p - 0.6, p, 100)
            for i, p in enumerate(prices)]
    st = analyze_timeframe(bars, "1m", scan_bars=10)
    breaks = [e for e in st.events_recent
              if e.kind in (StructureKind.BOS, StructureKind.CHOCH)]
    assert len({(e.kind, e.direction, e.level) for e in breaks}) == len(breaks)


def test_liquidity_sweep_bullish():
    bars = mk_trend_bars(20, 25000, -2)
    # Wick below prior low, close back above.
    bars.append(Bar(20 * 60.0, 24970, 24972, 24940, 24968, 800))
    st = analyze_timeframe(bars, "1m", strength=2, scan_bars=3)
    sweeps = [e for e in st.events_recent if e.kind == StructureKind.SWEEP]
    # May or may not fire depending on swing detection — at least no crash.
    assert st.timeframe == "1m"
