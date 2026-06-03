"""Tests for the Change of Character (CHoCH) indicator."""
import numpy as np
import pandas as pd

from src.indicators.choch import detect_recent_choch


def _bearish_choch_df() -> pd.DataFrame:
    """Uptrend → pullback → new high (BOS) → reversal below prior swing low (bearish CHoCH).

    Verified: with swing_length=10, lookback=15, n=185 bars, the bearish CHoCH
    BrokenIndex is at bar 176 (9 bars from end) → recent=True.
    """
    n = 185
    close = np.zeros(n)
    close[0:50]   = np.linspace(1.00, 1.10, 50)   # initial uptrend
    close[50:80]  = np.linspace(1.10, 1.05, 30)   # pullback (swing low ~1.048)
    close[80:130] = np.linspace(1.05, 1.15, 50)   # new high → BOS up
    close[130:]   = np.linspace(1.15, 1.03, n - 130)  # reversal below prior swing low
    return pd.DataFrame({
        "open":   close - 0.001,
        "high":   close + 0.002,
        "low":    close - 0.002,
        "close":  close,
        "volume": np.full(n, 5000.0),
    })


def _bullish_choch_df() -> pd.DataFrame:
    """Downtrend → pullback → new low (BOS) → reversal above prior swing high (bullish CHoCH)."""
    n = 185
    close = np.zeros(n)
    close[0:50]   = np.linspace(1.15, 1.05, 50)   # initial downtrend
    close[50:80]  = np.linspace(1.05, 1.10, 30)   # pullback (swing high ~1.098)
    close[80:130] = np.linspace(1.10, 1.00, 50)   # new low → BOS down
    close[130:]   = np.linspace(1.00, 1.12, n - 130)  # reversal above prior swing high
    return pd.DataFrame({
        "open":   close + 0.001,
        "high":   close + 0.002,
        "low":    close - 0.002,
        "close":  close,
        "volume": np.full(n, 5000.0),
    })


def test_detects_recent_bearish_choch():
    """Bearish CHoCH within lookback window should return 'bearish'."""
    result = detect_recent_choch(_bearish_choch_df(), swing_length=10, lookback=15)
    assert result == "bearish"


def test_detects_recent_bullish_choch():
    """Bullish CHoCH within lookback window should return 'bullish'."""
    result = detect_recent_choch(_bullish_choch_df(), swing_length=10, lookback=15)
    assert result == "bullish"


def test_old_choch_outside_lookback_returns_none():
    """CHoCH beyond the lookback window should be ignored — return None."""
    df = _bearish_choch_df()
    # Extend the df by 50 bars so the CHoCH (BrokenIndex ~176) is now > 15 bars old
    extra = pd.DataFrame({
        "open": [1.03] * 50, "high": [1.032] * 50,
        "low": [1.028] * 50, "close": [1.03] * 50,
        "volume": [5000.0] * 50,
    })
    extended = pd.concat([df, extra], ignore_index=True)
    result = detect_recent_choch(extended, swing_length=10, lookback=15)
    assert result is None


def test_no_choch_in_trending_market_returns_none():
    """A clean linear trend has no CHoCH — should return None."""
    n = 200
    close = np.linspace(1.00, 1.20, n)   # pure uptrend, no reversal
    df = pd.DataFrame({
        "open":   close - 0.001, "high": close + 0.002,
        "low":    close - 0.002, "close": close,
        "volume": np.full(n, 5000.0),
    })
    result = detect_recent_choch(df)
    assert result is None


def test_fails_open_on_too_short_df():
    """If df is too short to compute CHoCH, return None (fail-open)."""
    tiny = pd.DataFrame({
        "open": [1.10, 1.11], "high": [1.11, 1.12],
        "low": [1.09, 1.10], "close": [1.105, 1.115],
        "volume": [1000.0, 1000.0],
    })
    assert detect_recent_choch(tiny) is None
