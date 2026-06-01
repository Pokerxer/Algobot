from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import pandas_ta as ta

from src.config.schema import AppConfig
from src.models.regime import Regime, RegimeState
from src.regime.indicators import compute_atr, compute_adx
from src.strategies.base import BaseStrategy
from src.strategies.momentum import _adx_is_rising, _SLOPE_MIN_ATR, _volume_confirms_bounce

_TREND = (Regime.TRENDING_UP, Regime.TRENDING_DOWN)


@dataclass
class Evaluation:
    instrument: str
    regime: str
    in_session: bool
    strategy: Optional[str]
    status: str                       # 'signal' | 'gated' | 'no_setup'
    reason: str
    setup_distance: Optional[float]
    detail: dict = field(default_factory=dict)


def _gated(inst, regime, reason) -> Evaluation:
    return Evaluation(inst, regime.value, True, None, "gated", reason, None, {})


def evaluate(instrument: str, regime_state: RegimeState, entry_df: pd.DataFrame,
             cfg: AppConfig, strategy: Optional[BaseStrategy], *,
             in_session: bool, allowed_regimes, mtf_aligned: Optional[bool],
             is_mean_rev_only: bool, is_momentum_only: bool) -> Evaluation:
    """Build the per-instrument evaluation. `status` uses the real strategy's
    generate_signal verdict so it can never disagree with live trading; the
    reason/setup_distance/detail are display-only breakdowns."""
    regime = regime_state.regime

    # ── gates (mirror run_cycle order) ──
    if not in_session:
        return Evaluation(instrument, regime.value, False, None, "gated",
                          "out of session window", None, {})
    if is_mean_rev_only and regime in _TREND:
        return _gated(instrument, regime, "mean-reversion-only pair, regime trending")
    if is_momentum_only and regime == Regime.RANGING:
        return _gated(instrument, regime, "momentum-only pair, regime ranging")
    if allowed_regimes is not None and regime not in allowed_regimes:
        return _gated(instrument, regime, f"session-regime gate: {regime.value} not allowed this hour")
    if regime in _TREND and mtf_aligned is False:
        return _gated(instrument, regime, "H4/D1 not aligned")

    # ── reached the strategy: real verdict drives status ──
    if strategy is None:
        return _gated(instrument, regime, "no strategy for regime")
    would_signal = strategy.generate_signal(entry_df, regime_state) is not None

    if regime in (Regime.RANGING, Regime.CHOPPY):
        return _mr_eval(instrument, regime, entry_df, cfg.strategy.mean_reversion, would_signal)
    return _mom_eval(instrument, regime, entry_df, cfg.strategy.momentum, would_signal)


def _mr_eval(inst, regime, df, c, would_signal) -> Evaluation:
    rname, strat = regime.value, "mean_reversion"
    rsi = ta.rsi(df["close"], length=c.rsi_period)
    bb = ta.bbands(df["close"], length=20, std=c.bb_std)
    if rsi is None or bb is None or bool(rsi.isna().iloc[-1]):
        return Evaluation(inst, rname, True, strat, "no_setup", "insufficient indicator data", 0.0, {})
    bbl = next((x for x in bb.columns if x.startswith("BBL")), None)
    bbu = next((x for x in bb.columns if x.startswith("BBU")), None)
    if not bbl or not bbu:
        return Evaluation(inst, rname, True, strat, "no_setup", "bollinger columns missing", 0.0, {})

    close = float(df["close"].iloc[-1]); lower = float(bb[bbl].iloc[-1]); upper = float(bb[bbu].iloc[-1])
    rsi_now = float(rsi.iloc[-1])
    pct_b = (close - lower) / (upper - lower) if upper > lower else 0.5
    lower_touch, upper_touch = close <= lower, close >= upper
    pct_b_clamped = max(0.0, min(1.0, pct_b))
    distance = max(0.0, 1.0 - 2.0 * min(pct_b_clamped, 1.0 - pct_b_clamped))
    detail = {"pct_b": round(pct_b, 3), "rsi": round(rsi_now, 1),
              "lower_touch": lower_touch, "upper_touch": upper_touch,
              "rsi_oversold": c.rsi_oversold, "rsi_overbought": c.rsi_overbought}

    if would_signal:
        reason = "at band with RSI extreme - setup ready"
    elif not (lower_touch or upper_touch):
        reason = "price mid-band, not touching either band"
    elif lower_touch:
        reason = f"at lower band but RSI {rsi_now:.0f} not < {c.rsi_oversold:.0f}" \
                 if rsi_now >= c.rsi_oversold else "lower band touch - confirmation filters not met"
    else:
        reason = f"at upper band but RSI {rsi_now:.0f} not > {c.rsi_overbought:.0f}" \
                 if rsi_now <= c.rsi_overbought else "upper band touch - confirmation filters not met"

    return Evaluation(inst, rname, True, strat, "signal" if would_signal else "no_setup",
                      reason, round(distance, 3), detail)


def _mom_eval(inst, regime, df, c, would_signal) -> Evaluation:
    rname, strat = regime.value, "momentum"
    fast = ta.ema(df["close"], length=c.fast_ema)
    slow = ta.ema(df["close"], length=c.slow_ema)
    atr = compute_atr(df, period=14)
    rsi = ta.rsi(df["close"], length=c.rsi_period)
    if any(s is None or bool(s.isna().iloc[-1]) for s in (fast, slow, atr, rsi)):
        return Evaluation(inst, rname, True, strat, "no_setup", "insufficient indicator data", 0.0, {})

    close = float(df["close"].iloc[-1]); prev = float(df["close"].iloc[-2])
    prev2 = float(df["close"].iloc[-3]) if len(df) > 3 else prev
    fast_now = float(fast.iloc[-1]); slow_now = float(slow.iloc[-1]); atr_now = float(atr.iloc[-1]); rsi_now = float(rsi.iloc[-1])
    slow_10 = float(slow.iloc[-10]) if len(slow) > 10 else slow_now
    slope_atr = (slow_now - slow_10) / atr_now if atr_now > 0 else 0.0
    try:
        adx_rising = _adx_is_rising(compute_adx(df, 14)["adx"])
    except ValueError:
        adx_rising = True
    down = regime == Regime.TRENDING_DOWN
    ema_aligned = fast_now < slow_now if down else fast_now > slow_now
    slope_ok = slope_atr < -_SLOPE_MIN_ATR if down else slope_atr > _SLOPE_MIN_ATR
    rsi_ok = rsi_now < c.rsi_midline if down else rsi_now > c.rsi_midline
    if down:
        ema_touch = float(df["high"].iloc[-2]) >= fast_now * 0.999
        bounce = (close < prev) and (prev < prev2)
    else:
        ema_touch = float(df["low"].iloc[-2]) <= fast_now * 1.001
        bounce = (close > prev) and (prev > prev2)

    vol_ok = _volume_confirms_bounce(df)
    checks = [
        ("adx_rising", adx_rising, "ADX not rising"),
        ("ema_aligned", ema_aligned, "fast/slow EMA not aligned"),
        ("slope_ok", slope_ok, "slow-EMA slope too shallow"),
        ("rsi_ok", rsi_ok, "RSI not past midline"),
        ("ema_touch", ema_touch, "no pullback to fast EMA"),
        ("bounce", bounce, "no two-bar bounce"),
        ("vol_ok", vol_ok, "volume did not confirm bounce"),
    ]
    passed = sum(1 for _, ok, _ in checks if ok)
    detail = {k: ok for k, ok, _ in checks}
    detail.update({"slope_atr": round(slope_atr, 3), "rsi": round(rsi_now, 1)})

    if would_signal:
        reason = "trend + pullback aligned - setup ready"
    else:
        reason = next((msg for _, ok, msg in checks if not ok), "entry filters not met")

    return Evaluation(inst, rname, True, strat, "signal" if would_signal else "no_setup",
                      reason, round(passed / len(checks), 3), detail)
