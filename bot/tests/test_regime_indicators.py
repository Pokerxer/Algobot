import numpy as np
import pandas as pd
from src.regime.indicators import compute_adx, compute_bb_width, compute_atr


def _trending(n=200):
    close = np.linspace(1.0, 1.5, n)
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def _ranging(n=200):
    rng = np.random.default_rng(42)
    close = 1.0 + 0.01 * np.sin(np.linspace(0, 20, n)) + rng.normal(0, 0.0005, n)
    return pd.DataFrame({"open": close, "high": close + 0.002,
                         "low": close - 0.002, "close": close})


def test_adx_higher_for_trending():
    trend = compute_adx(_trending(), period=14)
    rng = compute_adx(_ranging(), period=14)
    assert trend["adx"].iloc[-1] > rng["adx"].iloc[-1]


def test_adx_returns_di_components():
    out = compute_adx(_trending(), period=14)
    assert {"adx", "plus_di", "minus_di"}.issubset(out.columns)
    assert out["plus_di"].iloc[-1] > out["minus_di"].iloc[-1]


def test_bb_width_computable():
    width = compute_bb_width(_trending(), period=20, std=2.0)
    assert not width.isna().all()


def test_atr_positive():
    atr = compute_atr(_trending(), period=14)
    assert (atr.dropna() > 0).all()
