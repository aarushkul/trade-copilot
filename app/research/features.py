"""Causal per-minute feature matrix over the research corpus.

One row per 1m bar. Everything in a row is computable from bars up to and
including that bar plus prior sessions — no forward information (enforced by
the anti-lookahead test, tests/test_research_features.py). Forward-looking
targets live in outcomes.py, in a separate file, on purpose.

Cached to data/research/features/v{FEATURE_VERSION}/{split}.parquet.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.indicators.noise import NoiseBands
from app.models import Bar

FEATURE_VERSION = 1
ET = ZoneInfo("America/New_York")

RTH_OPEN_MIN = 9 * 60 + 30    # minutes after ET midnight
RTH_CLOSE_MIN = 16 * 60


class _Ema:
    def __init__(self, period: int):
        self.k = 2.0 / (period + 1)
        self.v: float | None = None

    def push(self, x: float) -> float:
        self.v = x if self.v is None else self.v + self.k * (x - self.v)
        return self.v


class _Wilder:
    """Wilder smoothing for RSI/ATR."""

    def __init__(self, period: int):
        self.period = period
        self.v: float | None = None
        self._seed: list[float] = []

    def push(self, x: float) -> float | None:
        if self.v is None:
            self._seed.append(x)
            if len(self._seed) == self.period:
                self.v = sum(self._seed) / self.period
            return self.v
        self.v = (self.v * (self.period - 1) + x) / self.period
        return self.v


class _Rsi:
    def __init__(self, period: int = 14):
        self.up = _Wilder(period)
        self.dn = _Wilder(period)
        self.prev: float | None = None

    def push(self, close: float) -> float:
        if self.prev is None:
            self.prev = close
            return 50.0
        ch = close - self.prev
        self.prev = close
        u = self.up.push(max(ch, 0.0))
        d = self.dn.push(max(-ch, 0.0))
        if u is None or d is None or (u + d) == 0:
            return 50.0
        return 100.0 * u / (u + d)


class _CausalSwings:
    """Strength-k fractal pivots that only become visible k bars later."""

    def __init__(self, strength: int = 3):
        self.k = strength
        self.h: list[float] = []
        self.l: list[float] = []
        self.last_high: float = math.nan
        self.last_low: float = math.nan

    def push(self, high: float, low: float) -> None:
        self.h.append(high)
        self.l.append(low)
        i = len(self.h) - 1 - self.k          # candidate pivot index
        if i < self.k:
            return
        win_h = self.h[i - self.k:i + self.k + 1]
        win_l = self.l[i - self.k:i + self.k + 1]
        if self.h[i] == max(win_h):
            self.last_high = self.h[i]
        if self.l[i] == min(win_l):
            self.last_low = self.l[i]


class _Composite:
    """Aggregate 1m bars into n-minute composites keyed by wall clock."""

    def __init__(self, minutes: int):
        self.n = minutes * 60
        self.bucket: float | None = None
        self.o = self.h = self.l = self.c = 0.0
        self.closed: tuple[float, float, float, float] | None = None

    def push(self, bar: Bar) -> bool:
        b = bar.ts - (bar.ts % self.n)
        rolled = False
        if self.bucket is None or b != self.bucket:
            if self.bucket is not None:
                self.closed = (self.o, self.h, self.l, self.c)
                rolled = True
            self.bucket, self.o, self.h, self.l, self.c = b, bar.open, bar.high, bar.low, bar.close
        else:
            self.h = max(self.h, bar.high)
            self.l = min(self.l, bar.low)
            self.c = bar.close
        return rolled


COLUMNS = [
    "ts", "minute_et", "minute_of_rth", "dow", "is_rth", "close",
    "ret_1m", "ret_5m", "ret_15m", "ret_30m", "rvol_30m",
    "atr_1m", "atr_5m", "bar_range_atr", "body_frac",
    "vwap_dist_sigma", "vwap_side_min", "sigma_pts",
    "noise_pos", "noise_halfwidth_atr", "noise_cross_up", "noise_cross_dn",
    "mins_beyond_band",
    "rvol_1m", "cumvol_vs_14d",
    "ema9_1m_dist_atr", "ema21_1m_dist_atr", "ema21_1m_slope",
    "ema9_5m_dist_atr", "ema21_5m_dist_atr", "rsi_1m",
    "swing1m_high_dist_atr", "swing1m_low_dist_atr",
    "swing5m_high_dist_atr", "swing5m_low_dist_atr",
    "swing15m_high_dist_atr", "swing15m_low_dist_atr",
    "bos_up_1m", "bos_dn_1m", "bos_up_5m", "bos_dn_5m",
    "pdh_dist_atr", "pdl_dist_atr", "pdc_dist_atr",
    "onh_dist_atr", "onl_dist_atr",
    "or5_pos", "or15_pos", "or30_pos", "or15_width_vs_med",
    "gap_atr", "open_drive_atr", "open_drive_band",
]


def build_session(bars: list[Bar], noise: NoiseBands,
                  prev_rth: dict | None, or15_med: float | None) -> pd.DataFrame:
    """Feature rows for one session. `noise` must already hold ONLY prior
    sessions; this function feeds it the current session's RTH bars as it
    walks (bands_at uses prior sessions only — NoiseBands averages stored
    session profiles, and the current session is appended at session end)."""
    n = len(bars)
    out = {c: np.full(n, np.nan, dtype=np.float64) for c in COLUMNS}
    closes: list[float] = []
    vols: list[int] = []
    ema9_1m, ema21_1m = _Ema(9), _Ema(21)
    ema9_5m, ema21_5m = _Ema(9), _Ema(21)
    rsi = _Rsi(14)
    atr1, atr5 = _Wilder(14), _Wilder(14)
    sw1, sw5, sw15 = _CausalSwings(3), _CausalSwings(2), _CausalSwings(2)
    comp5, comp15 = _Composite(5), _Composite(15)
    ema21_hist: list[float] = []
    prev_close: float | None = None
    prev5_close: float | None = None

    cum_pv = cum_v = cum_v2 = 0.0     # session vwap + sigma (volume-weighted)
    rth_open: float | None = None
    on_high = -math.inf
    on_low = math.inf
    or_levels: dict[int, list[float]] = {5: [-math.inf, math.inf],
                                         15: [-math.inf, math.inf],
                                         30: [-math.inf, math.inf]}
    side_since = 0
    prev_side = 0
    beyond_since = 0
    prev_beyond = 0
    cum_session_vol = 0.0

    for i, b in enumerate(bars):
        et = datetime.fromtimestamp(b.ts, tz=ET)
        minute_et = et.hour * 60 + et.minute
        is_rth = RTH_OPEN_MIN <= minute_et < RTH_CLOSE_MIN
        closes.append(b.close)
        vols.append(b.volume)
        cum_session_vol += b.volume

        tr = b.high - b.low if prev_close is None else max(
            b.high - b.low, abs(b.high - prev_close), abs(b.low - prev_close))
        a1 = atr1.push(tr)
        e9 = ema9_1m.push(b.close)
        e21 = ema21_1m.push(b.close)
        ema21_hist.append(e21)
        r = rsi.push(b.close)
        sw1.push(b.high, b.low)

        if comp5.push(b) and comp5.closed:
            o, h, l, c = comp5.closed
            tr5 = h - l if prev5_close is None else max(h - l, abs(h - prev5_close), abs(l - prev5_close))
            atr5.push(tr5)
            ema9_5m.push(c)
            ema21_5m.push(c)
            sw5.push(h, l)
            prev5_close = c
        if comp15.push(b) and comp15.closed:
            _, h, l, _ = comp15.closed
            sw15.push(h, l)

        tp = (b.high + b.low + b.close) / 3.0
        cum_pv += tp * b.volume
        cum_v += b.volume
        cum_v2 += tp * tp * b.volume
        vwap = cum_pv / cum_v if cum_v else b.close
        var = max(cum_v2 / cum_v - vwap * vwap, 0.0) if cum_v else 0.0
        sigma = math.sqrt(var)

        if is_rth and rth_open is None:
            rth_open = b.open
        if not is_rth and rth_open is None:      # overnight, before the open
            on_high = max(on_high, b.high)
            on_low = min(on_low, b.low)
        if rth_open is not None:
            rth_min = minute_et - RTH_OPEN_MIN
            for length, lv in or_levels.items():
                if rth_min < length:
                    lv[0] = max(lv[0], b.high)
                    lv[1] = min(lv[1], b.low)

        band = noise.bands_at(b.ts) if is_rth else None
        noise.on_minute_bar(b)

        a5 = atr5.v
        safe_a5 = a5 if a5 else (a1 if a1 else 1.0)
        row_i = out
        row_i["ts"][i] = b.ts
        row_i["minute_et"][i] = minute_et
        row_i["minute_of_rth"][i] = (minute_et - RTH_OPEN_MIN) if is_rth else -1
        row_i["dow"][i] = et.weekday()
        row_i["is_rth"][i] = 1.0 if is_rth else 0.0
        row_i["close"][i] = b.close
        if len(closes) > 1:
            row_i["ret_1m"][i] = closes[-1] - closes[-2]
        for lag, col in ((5, "ret_5m"), (15, "ret_15m"), (30, "ret_30m")):
            if len(closes) > lag:
                row_i[col][i] = closes[-1] - closes[-1 - lag]
        if len(closes) > 30:
            rets = np.diff(closes[-31:])
            row_i["rvol_30m"][i] = float(np.std(rets))
        if a1:
            row_i["atr_1m"][i] = a1
            row_i["bar_range_atr"][i] = (b.high - b.low) / a1 if a1 else np.nan
        if a5:
            row_i["atr_5m"][i] = a5
        rng = b.high - b.low
        row_i["body_frac"][i] = abs(b.close - b.open) / rng if rng > 0 else 0.0

        if sigma > 0:
            row_i["vwap_dist_sigma"][i] = (b.close - vwap) / sigma
        side = 1 if b.close > vwap else (-1 if b.close < vwap else 0)
        side_since = side_since + 1 if side and side == prev_side else (1 if side else 0)
        prev_side = side
        row_i["vwap_side_min"][i] = side_since
        row_i["sigma_pts"][i] = sigma

        if band and rth_open is not None:
            lo, hi = band
            half = (hi - lo) / 2.0
            mid = (hi + lo) / 2.0
            pos = (b.close - mid) / half if half > 0 else 0.0
            row_i["noise_pos"][i] = pos
            row_i["noise_halfwidth_atr"][i] = half / safe_a5
            beyond = 1 if abs(pos) > 1.0 else 0
            row_i["noise_cross_up"][i] = 1.0 if (pos > 1.0 and prev_beyond <= 0) else 0.0
            row_i["noise_cross_dn"][i] = 1.0 if (pos < -1.0 and prev_beyond >= 0) else 0.0
            beyond_since = beyond_since + 1 if beyond else 0
            prev_beyond = np.sign(pos) if abs(pos) > 1.0 else 0
            row_i["mins_beyond_band"][i] = beyond_since

        if len(vols) > 20:
            base = np.mean(vols[-21:-1])
            row_i["rvol_1m"][i] = b.volume / base if base else np.nan
        if a1:
            row_i["ema9_1m_dist_atr"][i] = (b.close - e9) / a1
            row_i["ema21_1m_dist_atr"][i] = (b.close - e21) / a1
            if len(ema21_hist) > 5:
                row_i["ema21_1m_slope"][i] = (e21 - ema21_hist[-6]) / a1
        if ema9_5m.v is not None and a5:
            row_i["ema9_5m_dist_atr"][i] = (b.close - ema9_5m.v) / a5
            row_i["ema21_5m_dist_atr"][i] = (b.close - ema21_5m.v) / a5
        row_i["rsi_1m"][i] = r

        for sw, tag in ((sw1, "swing1m"), (sw5, "swing5m"), (sw15, "swing15m")):
            if not math.isnan(sw.last_high):
                row_i[f"{tag}_high_dist_atr"][i] = (sw.last_high - b.close) / safe_a5
            if not math.isnan(sw.last_low):
                row_i[f"{tag}_low_dist_atr"][i] = (b.close - sw.last_low) / safe_a5
        row_i["bos_up_1m"][i] = 1.0 if (not math.isnan(sw1.last_high) and b.close > sw1.last_high) else 0.0
        row_i["bos_dn_1m"][i] = 1.0 if (not math.isnan(sw1.last_low) and b.close < sw1.last_low) else 0.0
        row_i["bos_up_5m"][i] = 1.0 if (not math.isnan(sw5.last_high) and b.close > sw5.last_high) else 0.0
        row_i["bos_dn_5m"][i] = 1.0 if (not math.isnan(sw5.last_low) and b.close < sw5.last_low) else 0.0

        if prev_rth:
            row_i["pdh_dist_atr"][i] = (prev_rth["high"] - b.close) / safe_a5
            row_i["pdl_dist_atr"][i] = (b.close - prev_rth["low"]) / safe_a5
            row_i["pdc_dist_atr"][i] = (b.close - prev_rth["close"]) / safe_a5
        if on_high > -math.inf:
            row_i["onh_dist_atr"][i] = (on_high - b.close) / safe_a5
            row_i["onl_dist_atr"][i] = (b.close - on_low) / safe_a5

        if rth_open is not None and is_rth:
            rth_min = minute_et - RTH_OPEN_MIN
            for length, col in ((5, "or5_pos"), (15, "or15_pos"), (30, "or30_pos")):
                lv = or_levels[length]
                if rth_min >= length and lv[0] > -math.inf and lv[0] > lv[1]:
                    width = lv[0] - lv[1]
                    row_i[col][i] = (b.close - (lv[0] + lv[1]) / 2.0) / (width / 2.0)
            lv15 = or_levels[15]
            if rth_min >= 15 and or15_med and lv15[0] > lv15[1]:
                row_i["or15_width_vs_med"][i] = (lv15[0] - lv15[1]) / or15_med
            if prev_rth and a5:
                row_i["gap_atr"][i] = (rth_open - prev_rth["close"]) / safe_a5
            row_i["open_drive_atr"][i] = (b.close - rth_open) / safe_a5
            if band:
                lo, hi = band
                half = (hi - lo) / 2.0
                if half > 0:
                    row_i["open_drive_band"][i] = (b.close - rth_open) / half

        prev_close = b.close

    df = pd.DataFrame(out).astype(np.float32)
    df["ts"] = out["ts"]          # keep exact float64 — float32 loses ~200s
    return df


FEATURES_DIR_NAME = "features"


def _features_dir():
    from app.config import DATA_DIR
    d = DATA_DIR / "research" / FEATURES_DIR_NAME / f"v{FEATURE_VERSION}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_all(verbose: bool = True) -> dict[str, int]:
    """Walk the corpus chronologically, maintaining cross-session state
    (noise bands, prior-day levels, OR-width history), and write one parquet
    per split. Roll-flagged sessions FEED state but emit no rows — the live
    engine would have seen them, so state must too."""
    from collections import deque
    from statistics import median

    from app.research import data as datamod
    from app.research import splits

    all_sessions = datamod.sessions(include_roll=True)
    meta = datamod.session_meta()
    noise = NoiseBands()
    prev_rth: dict | None = None
    or15_hist: deque[float] = deque(maxlen=14)
    frames: dict[str, list[pd.DataFrame]] = {"train": [], "validation": [], "holdout": []}

    for sd in sorted(all_sessions):
        bars = all_sessions[sd]
        or15_med = median(or15_hist) if or15_hist else None
        df = build_session(bars, noise, prev_rth, or15_med)
        if not meta[sd].is_roll:
            df.insert(0, "session", sd)
            frames[splits.split_of(sd)].append(df)
        summ = session_rth_summary(bars)
        if summ:
            prev_rth = summ
            if summ.get("or15_width"):
                or15_hist.append(summ["or15_width"])

    counts = {}
    out = _features_dir()
    for split, fs in frames.items():
        if not fs:
            continue
        full = pd.concat(fs, ignore_index=True)
        full.to_parquet(out / f"{split}.parquet", index=False)
        counts[split] = len(full)
        if verbose:
            print(f"  {split}: {len(full):,} rows -> {out / f'{split}.parquet'}")
    return counts


def load_features(split: str, run_id: str | None = None) -> pd.DataFrame:
    """Split-fenced feature access — same guard as splits.load_sessions."""
    from app.research import ledger, splits

    if split in ("validation", "holdout"):
        if not run_id:
            raise splits.SplitViolation(
                f"{split} features require a ledger-registered run_id")
        reg = ledger.registration(run_id)
        if reg.get("split") != split:
            raise splits.SplitViolation(
                f"run_id {run_id} is for split {reg.get('split')!r}, not {split!r}")
    path = _features_dir() / f"{split}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} — run scripts/research/build_features.py")
    return pd.read_parquet(path)


def session_rth_summary(bars: list[Bar]) -> dict | None:
    """Prior-day reference levels for the NEXT session's features."""
    rth = [b for b in bars
           if RTH_OPEN_MIN <= (datetime.fromtimestamp(b.ts, tz=ET).hour * 60
                               + datetime.fromtimestamp(b.ts, tz=ET).minute) < RTH_CLOSE_MIN]
    if not rth:
        return None
    or15 = [b for b in rth[:15]]
    return {
        "high": max(b.high for b in rth),
        "low": min(b.low for b in rth),
        "close": rth[-1].close,
        "open": rth[0].open,
        "range": max(b.high for b in rth) - min(b.low for b in rth),
        "or15_width": (max(b.high for b in or15) - min(b.low for b in or15)) if or15 else None,
    }
