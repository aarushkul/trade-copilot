"""Noise-band tracker and strict-CHoCH structure behavior."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.indicators.noise import NoiseBands
from app.indicators.structure import StructureKind, analyze_timeframe
from app.models import Bar

ET = ZoneInfo("America/New_York")


def ts_et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=ET).timestamp()


def make_rth_session(day: datetime, open_px: float, drift_per_min: float) -> list[Bar]:
    """One RTH session of 1m bars drifting linearly from the open."""
    bars = []
    for i in range(390):
        ts = (day + timedelta(minutes=i)).timestamp()
        px = open_px + drift_per_min * i
        bars.append(Bar(ts, px, px + 1, px - 1, px + drift_per_min, 100))
    return bars


def test_noise_bands_need_min_sessions_then_scale_with_time_of_day():
    nb = NoiseBands(lookback_sessions=14, min_sessions=8)
    # Mon Jun 1 2026 .. 10 weekdays, each drifting 0.05 pts/min from open.
    day = datetime(2026, 6, 1, 9, 30, tzinfo=ET)
    fed, last_day = 0, day
    while fed < 10:
        if day.weekday() < 5:
            for b in make_rth_session(day, 23000.0, 0.05):
                nb.on_minute_bar(b)
            fed += 1
            last_day = day
        day += timedelta(days=1)
    assert nb.ready

    lo_early, hi_early = nb.bands_at(last_day.replace(hour=9, minute=45).timestamp())
    lo_late, hi_late = nb.bands_at(last_day.replace(hour=15, minute=0).timestamp())
    assert hi_early > nb.today_open > lo_early
    # Average move from open grows through the day -> band must widen.
    assert (hi_late - lo_late) > (hi_early - lo_early)
    # Outside RTH there is no band.
    assert nb.bands_at(last_day.replace(hour=17, minute=0).timestamp()) is None


def test_noise_bands_not_ready_early():
    nb = NoiseBands(min_sessions=8)
    day = datetime(2026, 6, 1, 9, 30, tzinfo=ET)
    for b in make_rth_session(day, 23000.0, 0.05):
        nb.on_minute_bar(b)
    assert not nb.ready
    assert nb.bands_at(day.replace(hour=12, minute=0).timestamp()) is None


def _ranging_bars(n: int = 60) -> list[Bar]:
    """Sideways tape with a final close poking above the last swing high."""
    bars = []
    base = ts_et(2026, 7, 6, 10, 0)
    for i in range(n):
        # Oscillate: swing highs ~23010, swing lows ~22990.
        phase = i % 10
        mid = 23000 + (5 - abs(phase - 5)) * 2 * (1 if (i // 10) % 2 == 0 else -1)
        bars.append(Bar(base + i * 60, mid, mid + 2, mid - 2, mid, 100))
    last = bars[-1]
    bars[-1] = Bar(last.ts, last.open, 23016, last.low, 23015, 100)  # range poke
    return bars


def test_strict_choch_ignores_ranging_breaks():
    bars = _ranging_bars()
    strict = analyze_timeframe(bars, "1m", strict_choch=True)
    loose = analyze_timeframe(bars, "1m", strict_choch=False)

    def chochs(st):
        return [e for e in st.events_recent if e.kind == StructureKind.CHOCH]

    # The legacy mode calls a ranging-range poke a "change of character";
    # strict mode must not (there was no established trend to change).
    assert len(chochs(strict)) <= len(chochs(loose))
    for ev in chochs(strict):
        assert ev.kind != StructureKind.CHOCH or strict.bias != "ranging" \
            or ev.bars_ago > 0  # no fresh CHoCH straight out of a range
