from typing import Optional
import pandas as pd
import pandas_ta as ta
from src.config.schema import MomentumStrategyConfig
from src.models.regime import Regime, RegimeState
from src.models.signal import Direction, Signal
from src.regime.indicators import compute_atr, compute_adx
from src.strategies.base import BaseStrategy

# Minimum slow-EMA slope in ATR units over the 10-bar lookback.
# Filters flat/grinding pseudo-trends without blocking genuine directional moves.
_SLOPE_MIN_ATR: float = 0.05


def _volume_confirms_bounce(df: pd.DataFrame, period: int = 20) -> bool:
    """Return True if volume confirms the pullback-and-bounce pattern.

    Weak selling on the pullback bar (bar[-2] volume < EMA) combined with strong
    buying on the bounce bar (bar[-1] volume > EMA) confirms institutional re-entry.
    Fails open (True) when volume column is absent or all-zero — MT5 tick volume
    is sometimes unavailable, and that should never block an otherwise valid signal.
    """
    if "volume" not in df.columns:
        return True
    vol = df["volume"]
    if float(vol.sum()) == 0.0:
        return True
    vol_ema = vol.ewm(span=period).mean()
    pullback_vol  = float(vol.iloc[-2])
    bounce_vol    = float(vol.iloc[-1])
    avg_pullback  = float(vol_ema.iloc[-2])
    avg_bounce    = float(vol_ema.iloc[-1])
    return pullback_vol < avg_pullback and bounce_vol > avg_bounce


def _adx_is_rising(adx_series: pd.Series, lookback: int = 3) -> bool:
    """Return True if the ADX at the last bar is strictly higher than `lookback` bars ago.

    Fails open (True) when the series is too short to compare — insufficient data
    should not block signal generation.
    """
    if len(adx_series) < lookback + 1:
        return True
    tail = adx_series.iloc[-lookback]
    if pd.isna(tail):
        return True
    return float(adx_series.iloc[-1]) > float(tail)


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def __init__(self, config: MomentumStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if regime.regime not in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
            return None

        fast = ta.ema(df["close"], length=self._cfg.fast_ema)
        slow = ta.ema(df["close"], length=self._cfg.slow_ema)
        atr  = compute_atr(df, period=14)
        rsi  = ta.rsi(df["close"], length=self._cfg.rsi_period)

        if fast is None or slow is None or atr is None or rsi is None:
            return None
        if fast.isna().iloc[-1] or slow.isna().iloc[-1] or atr.isna().iloc[-1] or rsi.isna().iloc[-1]:
            return None

        close      = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        fast_now   = float(fast.iloc[-1])
        slow_now   = float(slow.iloc[-1])
        atr_now    = float(atr.iloc[-1])
        rsi_now    = float(rsi.iloc[-1])

        # ADX must be rising — declining ADX means the trend is losing strength
        try:
            adx_series = compute_adx(df, 14)["adx"]
        except ValueError:
            adx_series = pd.Series(dtype=float)
        if not _adx_is_rising(adx_series):
            return None

        # Slow EMA slope normalized by ATR — filters flat/grinding pseudo-trends.
        # A genuine trend moves the EMA by at least _SLOPE_MIN_ATR units of current ATR
        # over the 10-bar lookback window.
        slow_5 = float(slow.iloc[-10]) if len(slow) > 10 else slow_now
        slope_atr = (slow_now - slow_5) / atr_now if atr_now > 0 else 0.0

        if regime.regime == Regime.TRENDING_UP and fast_now > slow_now:
            if slope_atr < _SLOPE_MIN_ATR:
                return None
            # RSI must be recovering from a pullback (not already extended)
            if rsi_now < self._cfg.rsi_midline:
                return None
            # Strict EMA touch: low must be at or below the fast EMA (0.1% tolerance)
            touched  = float(df["low"].iloc[-2]) <= fast_now * 1.001
            # Two consecutive closing bounces — not just a single candle spike
            prev2_close = float(df["close"].iloc[-3]) if len(df) > 3 else prev_close
            bouncing = (close > prev_close) and (prev_close > prev2_close)
            if touched and bouncing:
                if not _volume_confirms_bounce(df):
                    return None
                stop   = close - self._cfg.atr_stop_multiplier * atr_now
                target = close + self._cfg.atr_target_multiplier * atr_now
                return Signal(
                    instrument=regime.instrument, direction=Direction.BUY,
                    entry_price=close, stop_loss=stop, take_profit=target,
                    confidence=regime.confidence, regime=regime.regime, strategy=self.name,
                )

        if regime.regime == Regime.TRENDING_DOWN and fast_now < slow_now:
            if slope_atr > -_SLOPE_MIN_ATR:   # EMA not falling steeply enough
                return None
            # RSI must confirm downward momentum
            if rsi_now > self._cfg.rsi_midline:
                return None
            touched  = float(df["high"].iloc[-2]) >= fast_now * 0.999
            prev2_close = float(df["close"].iloc[-3]) if len(df) > 3 else prev_close
            bouncing = (close < prev_close) and (prev_close < prev2_close)
            if touched and bouncing:
                if not _volume_confirms_bounce(df):
                    return None
                stop   = close + self._cfg.atr_stop_multiplier * atr_now
                target = close - self._cfg.atr_target_multiplier * atr_now
                return Signal(
                    instrument=regime.instrument, direction=Direction.SELL,
                    entry_price=close, stop_loss=stop, take_profit=target,
                    confidence=regime.confidence, regime=regime.regime, strategy=self.name,
                )

        return None
