"""Tests for the order block indicator wrapper."""
import numpy as np
import pandas as pd

from src.indicators.order_blocks import price_at_bullish_ob, price_at_bearish_ob


# ── fixtures ──────────────────────────────────────────────────────────────────

def _bullish_ob_df():
    """DataFrame with a fresh (unmitigated) bullish OB at bar 80.

    Structure: flat → downtrend 1.10→1.07 → rally to 1.12 (stays above OB).
    Bullish OB at bar 80 (Bottom≈1.0696, Top≈1.0704), MitigatedIndex=0.
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


def _bearish_ob_df():
    """DataFrame with a fresh (unmitigated) bearish OB at bar 60.

    Truncated at bar 89 — before the bull rally mitigates the bearish OB at bar 92.
    Bearish OB at bar 60 (Bottom≈1.0996, Top≈1.1004), MitigatedIndex=0.
    """
    n_full = 200
    close = np.ones(n_full) * 1.10
    close[60:80]  = np.linspace(1.10, 1.07, 20)
    close[80:100] = np.linspace(1.07, 1.12, 20)
    close[100:]   = 1.12
    # Truncate at bar 89 (rally has started but hasn't yet exceeded 1.10)
    close_trunc = close[:89]
    return pd.DataFrame({
        "open":   close_trunc - 0.0002,
        "high":   close_trunc + 0.0004,
        "low":    close_trunc - 0.0004,
        "close":  close_trunc,
        "volume": np.full(89, 5000.0),
    })


def _mitigated_bullish_ob_df():
    """DataFrame where a bullish OB is formed then price returns and closes through it.

    After the OB forms at bar 80, price drops back below OB bottom — MitigatedIndex>0.
    """
    n = 250
    close = np.ones(n) * 1.10
    close[60:80]   = np.linspace(1.10, 1.07, 20)   # bear trend → bullish OB at bar 80
    close[80:120]  = np.linspace(1.07, 1.15, 40)   # rally (OB created)
    close[120:160] = np.linspace(1.15, 1.06, 40)   # sell-off THROUGH the OB bottom
    close[160:]    = 1.06
    return pd.DataFrame({
        "open":   close - 0.001,
        "high":   close + 0.002,
        "low":    close - 0.003,
        "close":  close,
        "volume": np.full(n, 5000.0),
    })


# ── basic OB detection ────────────────────────────────────────────────────────

def test_price_at_bullish_ob_returns_true_when_in_zone():
    """Price at 1.07 (fresh bullish OB zone) should return True."""
    df = _bullish_ob_df()
    assert price_at_bullish_ob(df, 1.0700, lookback=50) is True


def test_price_at_bullish_ob_returns_false_when_price_above_all_obs():
    """Price at 1.20 is well above any OB zone — no institutional support there."""
    df = _bullish_ob_df()
    assert price_at_bullish_ob(df, 1.20, lookback=50) is False


def test_price_at_bearish_ob_returns_true_when_in_zone():
    """Price at 1.10 (fresh bearish OB zone) should return True."""
    df = _bearish_ob_df()
    assert price_at_bearish_ob(df, 1.1000, lookback=50) is True


def test_price_at_bearish_ob_returns_false_when_price_below_all_obs():
    """Price at 1.00 is well below any OB zone — no institutional resistance there."""
    df = _bearish_ob_df()
    assert price_at_bearish_ob(df, 1.00, lookback=50) is False


def test_fails_open_on_too_short_dataframe():
    """If df is too short to compute OBs, fail open (True) rather than blocking."""
    tiny = pd.DataFrame({
        "open": [1.10, 1.11], "high": [1.11, 1.12],
        "low": [1.09, 1.10], "close": [1.105, 1.115], "volume": [1000.0, 1000.0],
    })
    assert price_at_bullish_ob(tiny, 1.10) is True
    assert price_at_bearish_ob(tiny, 1.11) is True


# ── mitigated OB filtering ────────────────────────────────────────────────────

def test_mitigated_bullish_ob_is_excluded():
    """A bullish OB that price has closed through (MitigatedIndex > 0) must be excluded.

    The bot should return False — there's no fresh institutional support at a mitigated level.
    """
    df = _mitigated_bullish_ob_df()
    # Price at 1.07 (the old OB zone that was traded through)
    assert price_at_bullish_ob(df, 1.07, lookback=50) is False


# ── instrument-specific swing length ─────────────────────────────────────────

def test_xau_uses_wider_swing_length():
    """XAUUSDm should use swing_length=20 — verify no error and result is bool."""
    df = _bullish_ob_df()
    result = price_at_bullish_ob(df, 1.07, instrument="XAUUSDm", lookback=50)
    assert isinstance(result, bool)


def test_eurusd_uses_default_swing_length():
    """EURUSDm should use swing_length=10 (default)."""
    df = _bullish_ob_df()
    result = price_at_bullish_ob(df, 1.07, instrument="EURUSDm", lookback=50)
    assert isinstance(result, bool)
