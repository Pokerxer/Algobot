"""Master Trend Strategy — Pine 'Master Trend Strategy v1.1' port.

MT signal entries + stateful Rejection entries for USTECm / US30m on M15.
Chart visuals from the original script are intentionally not ported.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import pandas_ta as ta

from src.config.schema import MasterTrendStrategyConfig
from src.models.regime import RegimeState
from src.models.signal import Direction, Signal
from src.strategies.base import BaseStrategy

_MIN_BARS = 750


def _stoch_k(df: pd.DataFrame, length: int = 10, smooth: int = 3) -> pd.Series:
    """Pine ta.sma(ta.stoch(close, high, low, length), smooth)."""
    ll = df["low"].rolling(length).min()
    hh = df["high"].rolling(length).max()
    rng = (hh - ll).replace(0.0, float("nan"))
    raw = 100.0 * (df["close"] - ll) / rng
    return raw.rolling(smooth).mean()


def _session_vwap(df: pd.DataFrame) -> pd.Series:
    """hl2-weighted VWAP anchored to the UTC calendar day (Pine ta.vwap(hl2)).

    Falls back to equal weighting (running hl2 mean) when volume is missing or
    all-zero — MT5 tick volume is sometimes unavailable.
    """
    idx = df.index
    days = (idx.tz_convert("UTC").date if getattr(idx, "tz", None) is not None
            else idx.date)
    grp = pd.Series(days, index=df.index)
    hl2 = (df["high"] + df["low"]) / 2.0
    if "volume" in df.columns and float(df["volume"].sum()) > 0.0:
        vol = df["volume"].astype(float)
    else:
        vol = pd.Series(1.0, index=df.index)
    pv = (hl2 * vol).groupby(grp).cumsum()
    vv = vol.groupby(grp).cumsum()
    return pv / vv


def _bull_engulf(df: pd.DataFrame) -> pd.Series:
    o, c = df["open"], df["close"]
    o1, c1 = o.shift(1), c.shift(1)
    prev_bear = c1 < o1
    cur_bull = c > o
    return (prev_bear & cur_bull & (o <= c1) & (c >= o1)).fillna(False)


def _bear_engulf(df: pd.DataFrame) -> pd.Series:
    o, c = df["open"], df["close"]
    o1, c1 = o.shift(1), c.shift(1)
    prev_bull = c1 > o1
    cur_bear = c < o
    return (prev_bull & cur_bear & (o >= c1) & (c <= o1)).fillna(False)


def _compute(df: pd.DataFrame) -> pd.DataFrame:
    """Return df copy with bull_sig / bear_sig / ema750 columns."""
    out = df.copy()
    close = out["close"]
    rsi = ta.rsi(close, length=14)
    ema4 = ta.ema(close, length=4)
    ema5 = ta.ema(close, length=5)
    ema21 = ta.ema(close, length=21)
    sma50 = ta.sma(close, length=50)
    ema55 = ta.ema(close, length=55)
    ema89 = ta.ema(close, length=89)
    ema750 = ta.ema(close, length=750)

    cross_up = (ema4 > ema5) & (ema4.shift(1) <= ema5.shift(1))
    cross_dn = (ema4 < ema5) & (ema4.shift(1) >= ema5.shift(1))

    stok = _stoch_k(out)
    ema89_bull_bo = (close > ema89) & (close.shift(1) <= ema89.shift(1))
    ema89_bear_bo = (close < ema89) & (close.shift(1) >= ema89.shift(1))
    vwap = _session_vwap(out)
    vwap_up = (close > vwap) & (close.shift(1) <= vwap.shift(1))
    vwap_dn = (close < vwap) & (close.shift(1) >= vwap.shift(1))
    bull_valid = _bull_engulf(out) & (close > ema750)
    bear_valid = _bear_engulf(out) & (close < ema750)

    conf_bull = (stok > 52) | ema89_bull_bo | vwap_up | bull_valid
    conf_bear = (stok < 48) | ema89_bear_bo | vwap_dn | bear_valid

    out["ema750"] = ema750
    out["bull_sig"] = (
        cross_up & (rsi > 50)
        & (close > ema21) & (close > sma50) & (close > ema55)
        & (close > ema89) & (close > ema750) & conf_bull
    ).fillna(False)
    out["bear_sig"] = (
        cross_dn & (rsi < 50)
        & (close < ema21) & (close < sma50) & (close < ema55)
        & (close < ema89) & (close < ema750) & conf_bear
    ).fillna(False)
    return out


class MasterTrendStrategy(BaseStrategy):
    name = "master_trend"

    def __init__(self, config: MasterTrendStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if df is None or len(df) < _MIN_BARS:
            return None
        c = _compute(df)
        if bool(pd.isna(c["ema750"].iloc[-1])):
            return None

        close = float(c["close"].iloc[-1])
        cfg = self._cfg

        # ── MT signal entries (evaluated first, matching Pine ordering) ──
        if cfg.enable_mt_signals:
            if bool(c["bull_sig"].iloc[-1]) and cfg.enable_long:
                return self._signal(regime, Direction.BUY, close,
                                    cfg.tp_pct_mt, cfg.sl_pct_mt)
            if bool(c["bear_sig"].iloc[-1]) and cfg.enable_short:
                return self._signal(regime, Direction.SELL, close,
                                    cfg.tp_pct_mt, cfg.sl_pct_mt)

        # ── Rejection entries ──
        if cfg.enable_rejections:
            rej = self._rejection(c, regime)
            if rej is not None:
                return rej
        return None

    def _rejection(self, c: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        cfg = self._cfg
        last = len(c) - 1
        low = float(c["low"].iloc[last])
        high = float(c["high"].iloc[last])
        close = float(c["close"].iloc[last])
        ema750 = float(c["ema750"].iloc[last])
        ext = cfg.line_extension_bars

        opens = c["open"].to_numpy()
        bull = c["bull_sig"].to_numpy()
        bear = c["bear_sig"].to_numpy()

        # Iterate candidate line-origin bars newest-first (Pine order), within the
        # active window (start_bar < last <= start_bar + extension). Any MT line
        # (bull- or bear-drawn) can trigger either rejection direction — Pine
        # tests both conditions per line and breaks on the first detection;
        # the long/short toggle gates the ORDER, not the detection.
        first = max(0, last - ext)
        for j in range(last - 1, first - 1, -1):
            if not (bull[j] or bear[j]):
                continue
            line_price = float(opens[j])
            if low <= line_price < close and close > ema750:
                if not cfg.enable_long:
                    return None
                return self._signal(regime, Direction.BUY, close,
                                    cfg.tp_pct_rej, cfg.sl_pct_rej)
            if high >= line_price > close and close < ema750:
                if not cfg.enable_short:
                    return None
                return self._signal(regime, Direction.SELL, close,
                                    cfg.tp_pct_rej, cfg.sl_pct_rej)
        return None

    def _signal(self, regime: RegimeState, direction: Direction, close: float,
                tp_pct: float, sl_pct: float) -> Signal:
        if direction == Direction.BUY:
            tp = close * (1 + tp_pct / 100)
            sl = close * (1 - sl_pct / 100)
        else:
            tp = close * (1 - tp_pct / 100)
            sl = close * (1 + sl_pct / 100)
        return Signal(
            instrument=regime.instrument, direction=direction,
            entry_price=close, stop_loss=sl, take_profit=tp,
            confidence=regime.confidence, regime=regime.regime, strategy=self.name,
        )
