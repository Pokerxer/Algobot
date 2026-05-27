from typing import Optional
import pandas as pd
import pandas_ta as ta
from src.config.schema import MomentumStrategyConfig
from src.models.regime import Regime, RegimeState
from src.models.signal import Direction, Signal
from src.regime.indicators import compute_atr
from src.strategies.base import BaseStrategy


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def __init__(self, config: MomentumStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if regime.regime not in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
            return None

        fast = ta.ema(df["close"], length=self._cfg.fast_ema)
        slow = ta.ema(df["close"], length=self._cfg.slow_ema)
        atr = compute_atr(df, period=14)
        if fast is None or slow is None or atr is None:
            return None
        if fast.isna().iloc[-1] or slow.isna().iloc[-1] or atr.isna().iloc[-1]:
            return None

        close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        fast_now = float(fast.iloc[-1])
        slow_now = float(slow.iloc[-1])
        atr_now = float(atr.iloc[-1])

        if regime.regime == Regime.TRENDING_UP and fast_now > slow_now:
            touched = float(df["low"].iloc[-2]) <= fast_now * 1.002
            bouncing = close > prev_close
            if touched and bouncing:
                stop = close - self._cfg.atr_stop_multiplier * atr_now
                target = close + self._cfg.atr_target_multiplier * atr_now
                return Signal(
                    instrument=regime.instrument, direction=Direction.BUY,
                    entry_price=close, stop_loss=stop, take_profit=target,
                    confidence=regime.confidence, regime=regime.regime, strategy=self.name,
                )

        if regime.regime == Regime.TRENDING_DOWN and fast_now < slow_now:
            touched = float(df["high"].iloc[-2]) >= fast_now * 0.998
            bouncing = close < prev_close
            if touched and bouncing:
                stop = close + self._cfg.atr_stop_multiplier * atr_now
                target = close - self._cfg.atr_target_multiplier * atr_now
                return Signal(
                    instrument=regime.instrument, direction=Direction.SELL,
                    entry_price=close, stop_loss=stop, take_profit=target,
                    confidence=regime.confidence, regime=regime.regime, strategy=self.name,
                )

        return None
