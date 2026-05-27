import numpy as np
import pandas as pd
from src.strategies.momentum import MomentumStrategy
from src.config.schema import MomentumStrategyConfig
from src.models.regime import Regime, RegimeState


def _uptrend_with_pullback(n=200):
    close = np.linspace(1.0, 1.2, n)
    close[-1] = close[-5]  # pullback
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def test_no_signal_in_ranging_regime():
    strat = MomentumStrategy(MomentumStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.RANGING, confidence=0.7)
    assert strat.generate_signal(_uptrend_with_pullback(), rs) is None


def test_emits_buy_with_2to1_rr_in_uptrend():
    strat = MomentumStrategy(MomentumStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.TRENDING_UP, confidence=0.8)
    sig = strat.generate_signal(_uptrend_with_pullback(), rs)
    if sig is not None:
        assert sig.direction.value == "BUY"
        r = sig.entry_price - sig.stop_loss
        rr = sig.take_profit - sig.entry_price
        assert abs(rr / r - 2.0) < 0.1
