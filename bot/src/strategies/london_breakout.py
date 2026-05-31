from datetime import timezone
from typing import Optional

import pandas as pd

from src.config.schema import LondonBreakoutStrategyConfig
from src.models.regime import RegimeState
from src.models.signal import Direction, Signal
from src.strategies.base import BaseStrategy


def _pip_size(instrument: str) -> float:
    return 0.01 if "JPY" in instrument.upper() else 0.0001


class LondonBreakoutStrategy(BaseStrategy):
    name = "london_breakout"

    def __init__(self, config: LondonBreakoutStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if not isinstance(df.index, pd.DatetimeIndex):
            return None

        if len(df) == 0:
            return None

        last_ts = df.index[-1]
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        else:
            last_ts = last_ts.astimezone(timezone.utc)

        hour = last_ts.hour
        if hour < self._cfg.session_start_utc or hour >= self._cfg.session_end_utc:
            return None

        today = last_ts.date()
        idx_utc = df.index.tz_convert("UTC") if df.index.tz is not None else df.index
        asian_mask = (idx_utc.date == today) & (idx_utc.hour < self._cfg.session_start_utc)
        df_asian = df[asian_mask]

        if len(df_asian) < 3:
            return None

        asian_high = float(df_asian["high"].max())
        asian_low  = float(df_asian["low"].min())

        pip = _pip_size(regime.instrument)
        if (asian_high - asian_low) / pip < self._cfg.min_range_pips:
            return None

        close      = float(df["close"].iloc[-1])
        range_size = asian_high - asian_low

        if close > asian_high:
            return Signal(
                instrument=regime.instrument,
                direction=Direction.BUY,
                entry_price=close,
                stop_loss=asian_low,
                take_profit=close + range_size * self._cfg.tp_multiplier,
                confidence=regime.confidence,
                regime=regime.regime,
                strategy=self.name,
            )

        if close < asian_low:
            return Signal(
                instrument=regime.instrument,
                direction=Direction.SELL,
                entry_price=close,
                stop_loss=asian_high,
                take_profit=close - range_size * self._cfg.tp_multiplier,
                confidence=regime.confidence,
                regime=regime.regime,
                strategy=self.name,
            )

        return None
