"""Pure SMC entry strategy for XAUUSDm.

Entry: OB + liquidity sweep (stop-hunt and recover), D1 EMA-50 direction.
TP:    nearest unswept liquidity pool (buy-side for BUY, sell-side for SELL).
SL:    1.5 × ATR below/above entry.
Kill zone gated: London (07-10 UTC) or NY open (12-16 UTC) only.
"""
from __future__ import annotations
import logging
from typing import Optional
import pandas as pd
import pandas_ta as ta
from src.indicators.order_blocks import in_kill_zone
from src.models.regime import Regime, RegimeState
from src.models.signal import Direction, Signal
from src.regime.indicators import compute_atr
from src.strategies.base import BaseStrategy

log = logging.getLogger(__name__)

_OB_SWING = 20
_LIQ_SWING = 10
_MAX_ATR_TO_LIQ = 5.0
_FALLBACK_ATR_MULT = 4.0


def _nearest_liquidity(df: pd.DataFrame, entry: float, direction: str, atr: float) -> float:
    fallback = (entry + _FALLBACK_ATR_MULT * atr if direction == "BUY"
                else entry - _FALLBACK_ATR_MULT * atr)
    try:
        from smartmoneyconcepts import smc
        swing = smc.swing_highs_lows(df, swing_length=_LIQ_SWING)
        liq = smc.liquidity(df, swing)
        unswept = liq[(liq["Swept"] == 0) & liq["Liquidity"].notna() & (liq["Liquidity"] != 0)]
        if unswept.empty:
            return fallback
        if direction == "BUY":
            candidates = unswept[(unswept["Liquidity"] == 1) &
                                  (unswept["Level"] > entry) &
                                  (unswept["Level"] <= entry + _MAX_ATR_TO_LIQ * atr)]
            if not candidates.empty:
                return float(candidates.sort_values("Level").iloc[0]["Level"])
        else:
            candidates = unswept[(unswept["Liquidity"] == -1) &
                                  (unswept["Level"] < entry) &
                                  (unswept["Level"] >= entry - _MAX_ATR_TO_LIQ * atr)]
            if not candidates.empty:
                return float(candidates.sort_values("Level", ascending=False).iloc[0]["Level"])
    except Exception as exc:
        log.debug("Liquidity detection failed (%s) — using ATR fallback", exc)
    return fallback


def _d1_bullish(df: pd.DataFrame) -> Optional[bool]:
    try:
        d1 = (df.resample("1D")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna())
        if len(d1) < 15:
            return None
        ema = ta.ema(d1["close"], length=50)
        if ema is None or pd.isna(ema.iloc[-1]):
            return None
        return float(d1["close"].iloc[-1]) > float(ema.iloc[-1])
    except Exception:
        return None


class SMCGoldStrategy(BaseStrategy):
    """Pure SMC entry model for XAUUSDm — OB + sweep + D1 alignment."""
    name = "smc_gold"

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:  # noqa: C901
        if not in_kill_zone():
            return None
        if len(df) < 50:
            return None

        close     = float(df["close"].iloc[-1])
        prev_low  = float(df["low"].iloc[-2])
        prev_high = float(df["high"].iloc[-2])

        atr_s = compute_atr(df, period=14)
        if atr_s is None or pd.isna(atr_s.iloc[-1]):
            return None
        atr = float(atr_s.iloc[-1])

        bullish_d1 = _d1_bullish(df)

        try:
            from smartmoneyconcepts import smc
            swing = smc.swing_highs_lows(df, swing_length=_OB_SWING)
            ob_df = smc.ob(df, swing)
            ob_df = ob_df[ob_df["OB"].notna() & (ob_df["OB"] != 0)].copy()
        except Exception as exc:
            log.debug("OB computation failed for XAU (%s) — skipping", exc)
            return None

        if ob_df.empty:
            return None

        if bullish_d1 is not False:
            for _, row in ob_df[ob_df["OB"] == 1.0].tail(10).iterrows():
                bottom = float(row["Bottom"]); top = float(row["Top"])
                if not (bottom * 0.997 <= close <= top):
                    continue
                if not (prev_low <= bottom and close > bottom):
                    continue
                sl = close - 1.5 * atr
                if sl <= 0:
                    continue
                tp = _nearest_liquidity(df, close, "BUY", atr)
                if tp <= close:
                    tp = close + _FALLBACK_ATR_MULT * atr
                return Signal(instrument=regime.instrument, direction=Direction.BUY,
                              entry_price=close, stop_loss=round(sl, 2),
                              take_profit=round(tp, 2),
                              confidence=min(regime.confidence + 0.1, 1.0),
                              regime=regime.regime, strategy=self.name)

        if bullish_d1 is not True:
            for _, row in ob_df[ob_df["OB"] == -1.0].tail(10).iterrows():
                bottom = float(row["Bottom"]); top = float(row["Top"])
                if not (bottom <= close <= top * 1.003):
                    continue
                if not (prev_high >= top and close < top):
                    continue
                sl = close + 1.5 * atr
                tp = _nearest_liquidity(df, close, "SELL", atr)
                if tp >= close:
                    tp = close - _FALLBACK_ATR_MULT * atr
                if tp <= 0:
                    continue
                return Signal(instrument=regime.instrument, direction=Direction.SELL,
                              entry_price=close, stop_loss=round(sl, 2),
                              take_profit=round(tp, 2),
                              confidence=min(regime.confidence + 0.1, 1.0),
                              regime=regime.regime, strategy=self.name)

        return None
