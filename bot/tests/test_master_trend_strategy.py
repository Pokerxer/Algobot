import numpy as np
import pandas as pd
from datetime import timezone

from src.config.schema import MasterTrendStrategyConfig
from src.models.regime import Regime, RegimeState
from src.strategies.master_trend import MasterTrendStrategy, _compute


def _regime(instrument="USTECm"):
    return RegimeState(instrument=instrument, regime=Regime.TRENDING_UP, confidence=0.7)


def _strat(**over):
    return MasterTrendStrategy(MasterTrendStrategyConfig(**over))


def _uptrend_df(n=820, start=15000.0, step=3.0):
    """Long, steady uptrend so every EMA (incl. 750) is below price and rising.
    The final two bars force ema4-cross-above-ema5 by dipping then surging."""
    idx = pd.date_range("2026-06-01", periods=n, freq="15min", tz=timezone.utc)
    close = start + np.arange(n) * step
    close[-2] -= step * 4          # dip: pulls ema4 toward ema5
    close[-1] = close[-2] + step * 12  # surge: ema4 crosses above ema5, big bull close
    high = close + 2.0
    low = close - 2.0
    open_ = np.r_[close[0], close[:-1]]
    vol = np.full(n, 100.0)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def test_returns_none_below_min_bars():
    df = _uptrend_df(n=700)
    assert _strat().generate_signal(df, _regime()) is None


def test_mt_bull_signal_emits_buy_with_pct_tp_sl():
    df = _uptrend_df()
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert sig.direction.value == "BUY"
    assert sig.strategy == "master_trend"
    close = float(df["close"].iloc[-1])
    assert abs(sig.take_profit - close * 1.005) < 1e-6   # tp_pct_mt 0.5%
    assert abs(sig.stop_loss - close * 0.999) < 1e-6     # sl_pct_mt 0.1%


def test_enable_long_false_suppresses_buy():
    df = _uptrend_df()
    assert _strat(enable_long=False, enable_rejections=False).generate_signal(df, _regime()) is None


def test_strategy_name():
    assert _strat().name == "master_trend"


def test_bull_rejection_emits_buy():
    # Build an uptrend that fires an MT bull signal, then a later bar that wicks
    # down to that signal bar's open and closes back above it (and above ema750).
    df = _uptrend_df()
    c_pre = _compute(df)
    # find the last MT bull signal bar in the valid window (last 25 bars)
    sig_positions = [i for i in range(len(c_pre) - 26, len(c_pre) - 1)
                     if bool(c_pre["bull_sig"].iloc[i])]
    assert sig_positions, "fixture must contain an MT bull signal in the window"
    j = sig_positions[-1]
    line_price = float(df["open"].iloc[j])
    # append a rejection bar: low pierces the line, close recovers above it
    new_idx = df.index[-1] + pd.Timedelta("15min")
    close = line_price + 5.0
    rej_bar = pd.DataFrame(
        {"open": [line_price + 1], "high": [close + 2],
         "low": [line_price - 3], "close": [close], "volume": [100.0]},
        index=pd.DatetimeIndex([new_idx], tz=df.index.tz),
    )
    df2 = pd.concat([df, rej_bar])
    sig = _strat(enable_mt_signals=False).generate_signal(df2, _regime())
    assert sig is not None
    assert sig.direction.value == "BUY"
    assert abs(sig.take_profit - close * 1.003) < 1e-6   # tp_pct_rej 0.3%


def test_no_rejection_when_close_below_line():
    df = _uptrend_df()
    new_idx = df.index[-1] + pd.Timedelta("15min")
    # a bar that closes below every recent signal-bar open => no bull rejection
    low_close = float(df["open"].iloc[-30]) - 50.0
    rej_bar = pd.DataFrame(
        {"open": [low_close + 1], "high": [low_close + 2],
         "low": [low_close - 2], "close": [low_close], "volume": [100.0]},
        index=pd.DatetimeIndex([new_idx], tz=df.index.tz),
    )
    df2 = pd.concat([df, rej_bar])
    assert _strat(enable_mt_signals=False).generate_signal(df2, _regime()) is None
