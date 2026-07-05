import numpy as np
import pandas as pd
from datetime import timezone

from src.strategies.master_trend import (
    _stoch_k, _session_vwap, _bull_engulf, _bear_engulf,
)


def _df(o, h, l, c, vol=None, tz=True):
    n = len(c)
    idx = pd.date_range("2026-07-01", periods=n, freq="15min",
                        tz=timezone.utc if tz else None)
    data = {"open": o, "high": h, "low": l, "close": c}
    if vol is not None:
        data["volume"] = vol
    return pd.DataFrame(data, index=idx)


def test_stoch_k_matches_manual():
    # 12 bars; last bar close at the high of a rising range => %K near 100
    c = np.linspace(100, 111, 12)
    df = _df(c, c + 1, c - 1, c)
    k = _stoch_k(df, length=10, smooth=3)
    assert 90.0 <= float(k.iloc[-1]) <= 100.0
    assert k.iloc[:2].isna().all()  # warm-up NaNs before rolling windows fill


def test_session_vwap_resets_each_utc_day():
    # Day 1: two bars hl2=10; Day 2 first bar hl2=20 => vwap resets to 20 not blended
    idx = pd.DatetimeIndex([
        "2026-07-01 23:30", "2026-07-01 23:45", "2026-07-02 00:00",
    ], tz=timezone.utc)
    df = pd.DataFrame({
        "open": [10, 10, 20], "high": [11, 11, 21],
        "low": [9, 9, 19], "close": [10, 10, 20],
        "volume": [1, 1, 1],
    }, index=idx)
    v = _session_vwap(df)
    assert abs(float(v.iloc[-1]) - 20.0) < 1e-9


def test_bull_engulf_detects_pattern():
    # bar[-2] bearish (open 10 -> close 9); bar[-1] bullish engulf (open 9 -> close 10.5)
    df = _df([10, 10, 9], [10.1, 10.1, 10.6], [8.9, 8.9, 8.9], [10, 9, 10.5])
    assert bool(_bull_engulf(df).iloc[-1]) is True
    assert bool(_bear_engulf(df).iloc[-1]) is False
