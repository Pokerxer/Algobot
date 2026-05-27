from typing import Optional
import pandas as pd
import pandas_ta as ta
from src.config.schema import MeanReversionStrategyConfig
from src.models.regime import Regime, RegimeState
from src.models.signal import Direction, Signal
from src.regime.indicators import compute_atr
from src.strategies.base import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def __init__(self, config: MeanReversionStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if regime.regime != Regime.RANGING:
            return None

        rsi = ta.rsi(df["close"], length=self._cfg.rsi_period)
        bb = ta.bbands(df["close"], length=20, std=2.0)
        atr = compute_atr(df, period=14)
        if rsi is None or bb is None or atr is None:
            return None
        if rsi.isna().iloc[-1] or atr.isna().iloc[-1]:
            return None

        close = float(df["close"].iloc[-1])
        lower = float(bb["BBL_20_2.0_2.0"].iloc[-1])
        upper = float(bb["BBU_20_2.0_2.0"].iloc[-1])
        middle = float(bb["BBM_20_2.0_2.0"].iloc[-1])
        rsi_now = float(rsi.iloc[-1])
        atr_now = float(atr.iloc[-1])

        if close <= lower and rsi_now < self._cfg.rsi_oversold:
            return Signal(
                instrument=regime.instrument, direction=Direction.BUY,
                entry_price=close, stop_loss=lower - atr_now, take_profit=middle,
                confidence=regime.confidence, regime=regime.regime, strategy=self.name,
            )

        if close >= upper and rsi_now > self._cfg.rsi_overbought:
            return Signal(
                instrument=regime.instrument, direction=Direction.SELL,
                entry_price=close, stop_loss=upper + atr_now, take_profit=middle,
                confidence=regime.confidence, regime=regime.regime, strategy=self.name,
            )

        return None
