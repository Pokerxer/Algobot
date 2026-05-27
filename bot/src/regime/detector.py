import pandas as pd
from src.config.schema import RegimeConfig
from src.models.regime import Regime, RegimeState
from src.regime.indicators import compute_adx, compute_bb_width


class RegimeDetector:
    def __init__(self, config: RegimeConfig):
        self._cfg = config

    def classify(self, instrument: str, df: pd.DataFrame) -> RegimeState:
        adx_df = compute_adx(df, self._cfg.adx_period)
        bb_width = compute_bb_width(df, self._cfg.bb_period, self._cfg.bb_std)

        adx = float(adx_df["adx"].iloc[-1])
        plus_di = float(adx_df["plus_di"].iloc[-1])
        minus_di = float(adx_df["minus_di"].iloc[-1])
        width = float(bb_width.iloc[-1])
        width_median = float(bb_width.tail(30).median())
        width_90 = float(bb_width.quantile(0.90))

        if adx > self._cfg.adx_trend_threshold and max(plus_di, minus_di) > self._cfg.adx_range_threshold:
            regime = Regime.TRENDING_UP if plus_di > minus_di else Regime.TRENDING_DOWN
            confidence = min(1.0, (adx - self._cfg.adx_trend_threshold) / 25)
        elif adx < self._cfg.adx_range_threshold and width <= width_median:
            regime = Regime.RANGING
            confidence = min(1.0, (self._cfg.adx_range_threshold - adx) / 20)
        else:
            regime = Regime.CHOPPY
            confidence = 1.0 if width > width_90 else 0.5

        return RegimeState(
            instrument=instrument, regime=regime, confidence=confidence,
            indicators={"adx": adx, "plus_di": plus_di, "minus_di": minus_di,
                        "bb_width": width},
        )
