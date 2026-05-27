import numpy as np
import pandas as pd
from src.strategies.mean_reversion import MeanReversionStrategy
from src.config.schema import MeanReversionStrategyConfig
from src.models.regime import Regime, RegimeState


def _ranging_with_dip(n=200):
    rng = np.random.default_rng(7)
    close = 1.0 + 0.005 * np.sin(np.linspace(0, 20, n)) + rng.normal(0, 0.0002, n)
    close[-10:] = np.linspace(close[-11], close[-11] - 0.02, 10)
    return pd.DataFrame({"open": close, "high": close + 0.0005,
                         "low": close - 0.0005, "close": close})


def test_skips_trending_regime():
    strat = MeanReversionStrategy(MeanReversionStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.TRENDING_UP, confidence=0.8)
    assert strat.generate_signal(_ranging_with_dip(), rs) is None


def test_buys_on_oversold_lower_band():
    strat = MeanReversionStrategy(MeanReversionStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.RANGING, confidence=0.7)
    sig = strat.generate_signal(_ranging_with_dip(), rs)
    assert sig is not None
    assert sig.direction.value == "BUY"
    assert sig.stop_loss < sig.entry_price
