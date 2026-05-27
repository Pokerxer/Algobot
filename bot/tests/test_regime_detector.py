import numpy as np
import pandas as pd
from src.regime.detector import RegimeDetector
from src.config.schema import RegimeConfig
from src.models.regime import Regime


def _uptrend(n=200):
    close = np.linspace(1.0, 1.5, n)
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def _downtrend(n=200):
    close = np.linspace(1.5, 1.0, n)
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def _ranging(n=200):
    rng = np.random.default_rng(0)
    close = 1.0 + 0.005 * np.sin(np.linspace(0, 30, n)) + rng.normal(0, 0.0003, n)
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def test_detects_trending_up():
    rs = RegimeDetector(RegimeConfig()).classify("EURUSD", _uptrend())
    assert rs.regime == Regime.TRENDING_UP


def test_detects_trending_down():
    rs = RegimeDetector(RegimeConfig()).classify("EURUSD", _downtrend())
    assert rs.regime == Regime.TRENDING_DOWN


def test_detects_ranging_or_choppy():
    rs = RegimeDetector(RegimeConfig()).classify("EURUSD", _ranging())
    assert rs.regime in (Regime.RANGING, Regime.CHOPPY)


def test_returns_indicators_in_state():
    rs = RegimeDetector(RegimeConfig()).classify("EURUSD", _uptrend())
    assert "adx" in rs.indicators
    assert "bb_width" in rs.indicators
