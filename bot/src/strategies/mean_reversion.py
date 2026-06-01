from typing import Optional
import pandas as pd
import pandas_ta as ta
from src.config.schema import MeanReversionStrategyConfig
from src.models.regime import Regime, RegimeState
from src.models.signal import Direction, Signal
from src.regime.indicators import compute_atr
from src.strategies.base import BaseStrategy


def _rsi_diverges_bullish(rsi_series: pd.Series, prior_idx: int) -> bool:
    """Return True when the current RSI is strictly higher than RSI at `prior_idx`.

    A higher RSI at the second lower-band touch (less oversold) means the selling
    momentum is exhausting even as price retests the same level — bullish divergence.
    """
    return float(rsi_series.iloc[-1]) > float(rsi_series.iloc[prior_idx])


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def __init__(self, config: MeanReversionStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if regime.regime not in (Regime.RANGING, Regime.CHOPPY):
            return None

        rsi = ta.rsi(df["close"], length=self._cfg.rsi_period)
        bb  = ta.bbands(df["close"], length=20, std=self._cfg.bb_std)
        atr = compute_atr(df, period=14)

        if rsi is None or bb is None or atr is None:
            return None
        if rsi.isna().iloc[-1] or atr.isna().iloc[-1]:
            return None

        # Support both pandas_ta column name formats
        bb_l_col = next((c for c in bb.columns if c.startswith("BBL")), None)
        bb_u_col = next((c for c in bb.columns if c.startswith("BBU")), None)
        bb_m_col = next((c for c in bb.columns if c.startswith("BBM")), None)
        if not all([bb_l_col, bb_u_col, bb_m_col]):
            return None

        close  = float(df["close"].iloc[-1])
        lower  = float(bb[bb_l_col].iloc[-1])
        upper  = float(bb[bb_u_col].iloc[-1])
        middle = float(bb[bb_m_col].iloc[-1])
        rsi_now = float(rsi.iloc[-1])
        atr_now = float(atr.iloc[-1])

        # BB expansion filter — reject if bands are currently widening (volatility spike)
        if self._cfg.bb_expansion_filter and len(bb) >= 10:
            width_now  = upper - lower
            width_prev = float(bb[bb_u_col].iloc[-5]) - float(bb[bb_l_col].iloc[-5])
            if width_now > width_prev * 1.15:   # bands expanded >15% in 5 bars → skip
                return None

        # Double-touch confirmation — price must have previously tagged the band.
        # Returns the bar index of the prior touch (negative int) or None if not found.
        def _prior_touch_idx(side: str, lookback: int = 12) -> Optional[int]:
            for i in range(-lookback, -2):
                if side == "lower" and float(df["low"].iloc[i]) <= lower * 1.002:
                    return i
                if side == "upper" and float(df["high"].iloc[i]) >= upper * 0.998:
                    return i
            return None

        if close <= lower and rsi_now < self._cfg.rsi_oversold:
            prior_idx = _prior_touch_idx("lower")
            if self._cfg.require_double_touch and prior_idx is None:
                return None   # first touch only — wait for confirmation
            if self._cfg.require_divergence:
                if prior_idx is None:
                    return None   # divergence check requires a known prior touch
                if not _rsi_diverges_bullish(rsi, prior_idx):
                    return None   # RSI did not recover — no divergence
            return Signal(
                instrument=regime.instrument, direction=Direction.BUY,
                entry_price=close,
                stop_loss=lower - atr_now,
                take_profit=lower + (middle - lower) / 3,
                confidence=regime.confidence, regime=regime.regime, strategy=self.name,
            )

        if close >= upper and rsi_now > self._cfg.rsi_overbought:
            prior_idx = _prior_touch_idx("upper")
            if self._cfg.require_double_touch and prior_idx is None:
                return None
            if self._cfg.require_divergence:
                if prior_idx is None:
                    return None
                # Bearish divergence: RSI at second touch must be LOWER (less overbought)
                if float(rsi.iloc[-1]) >= float(rsi.iloc[prior_idx]):
                    return None
            return Signal(
                instrument=regime.instrument, direction=Direction.SELL,
                entry_price=close,
                stop_loss=upper + atr_now,
                take_profit=upper - (upper - middle) / 3,
                confidence=regime.confidence, regime=regime.regime, strategy=self.name,
            )

        return None
