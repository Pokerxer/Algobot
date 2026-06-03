"""Tests for the order block indicator wrapper."""
import numpy as np
import pandas as pd
import pytest

from src.indicators.order_blocks import price_at_bullish_ob, price_at_bearish_ob


def _ob_df():
    """Single DataFrame containing BOTH a bearish OB and a bullish OB.

    Structure:
      bars 0-59:   flat at 1.10
      bars 60-79:  downtrend 1.10 → 1.07  (bearish OB at bar 60: Top≈1.1004 Bottom≈1.0996)
      bars 80-99:  uptrend   1.07 → 1.12  (bullish OB at bar 80: Top≈1.0704 Bottom≈1.0696)
      bars 100-199: flat at 1.12

    Verified with swing_length=5 against smartmoneyconcepts 0.0.27.
    """
    n = 200
    close = np.ones(n) * 1.10
    close[60:80]  = np.linspace(1.10, 1.07, 20)
    close[80:100] = np.linspace(1.07, 1.12, 20)
    close[100:]   = 1.12
    return pd.DataFrame({
        "open":   close - 0.0002,
        "high":   close + 0.0004,
        "low":    close - 0.0004,
        "close":  close,
        "volume": np.full(n, 5000.0),
    })


def test_price_at_bullish_ob_returns_true_when_in_zone():
    """Price at 1.07 (bullish OB zone at bar 80) should return True."""
    df = _ob_df()
    assert price_at_bullish_ob(df, 1.0700, lookback=50) is True


def test_price_at_bullish_ob_returns_false_when_price_above_all_obs():
    """Price at 1.20 is well above any OB zone — no institutional support there."""
    df = _ob_df()
    assert price_at_bullish_ob(df, 1.20, lookback=50) is False


def test_price_at_bearish_ob_returns_true_when_in_zone():
    """Price at 1.10 (bearish OB zone at bar 60) should return True."""
    df = _ob_df()
    assert price_at_bearish_ob(df, 1.1000, lookback=50) is True


def test_price_at_bearish_ob_returns_false_when_price_below_all_obs():
    """Price at 1.00 is well below any OB zone — no institutional resistance there."""
    df = _ob_df()
    assert price_at_bearish_ob(df, 1.00, lookback=50) is False


def test_fails_open_on_too_short_dataframe():
    """If df is too short to compute OBs, fall through rather than blocking."""
    tiny = pd.DataFrame({
        "open":   [1.10, 1.11],
        "high":   [1.11, 1.12],
        "low":    [1.09, 1.10],
        "close":  [1.105, 1.115],
        "volume": [1000.0, 1000.0],
    })
    # Should fail open (True) rather than erroring or blocking
    assert price_at_bullish_ob(tiny, 1.10) is True
    assert price_at_bearish_ob(tiny, 1.11) is True
