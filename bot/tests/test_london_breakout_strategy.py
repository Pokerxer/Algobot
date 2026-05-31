from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.config.schema import LondonBreakoutStrategyConfig
from src.models.regime import Regime, RegimeState
from src.strategies.london_breakout import LondonBreakoutStrategy


def _regime(instrument: str = "EURUSDm") -> RegimeState:
    return RegimeState(instrument=instrument, regime=Regime.RANGING, confidence=0.75)


def _make_df(
    last_bar_hour: int,
    last_close: float,
    asian_high: float = 1.0850,
    asian_low: float = 1.0800,
) -> pd.DataFrame:
    """M15 DataFrame: 28 Asian bars (00:00-06:45 UTC) + 1 London bar at last_bar_hour."""
    today = datetime(2026, 5, 31, tzinfo=timezone.utc)
    asian_times = pd.date_range(
        start=today.replace(hour=0, minute=0),
        periods=28,
        freq="15min",
        tz=timezone.utc,
    )
    n = len(asian_times)
    asian_df = pd.DataFrame(
        {
            "open": np.full(n, 1.0825),
            "high": np.full(n, asian_high),
            "low": np.full(n, asian_low),
            "close": np.full(n, 1.0825),
        },
        index=asian_times,
    )
    london_time = today.replace(hour=last_bar_hour, minute=0)
    london_df = pd.DataFrame(
        {
            "open": [1.0840],
            "high": [last_close + 0.0002],
            "low": [last_close - 0.0002],
            "close": [last_close],
        },
        index=pd.DatetimeIndex([london_time], tz=timezone.utc),
    )
    return pd.concat([asian_df, london_df])


def _strat() -> LondonBreakoutStrategy:
    return LondonBreakoutStrategy(LondonBreakoutStrategyConfig())


# Time gate

def test_no_signal_before_london_open():
    df = _make_df(last_bar_hour=6, last_close=1.0860)
    assert _strat().generate_signal(df, _regime()) is None


def test_no_signal_at_or_after_window_close():
    df = _make_df(last_bar_hour=10, last_close=1.0860)
    assert _strat().generate_signal(df, _regime()) is None


# Price position

def test_no_signal_when_price_inside_range():
    df = _make_df(last_bar_hour=8, last_close=1.0825)  # inside [1.0800, 1.0850]
    assert _strat().generate_signal(df, _regime()) is None


def test_buy_signal_on_upside_break():
    df = _make_df(last_bar_hour=8, last_close=1.0860)  # above 1.0850
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert sig.direction.value == "BUY"


def test_sell_signal_on_downside_break():
    df = _make_df(last_bar_hour=8, last_close=1.0790)  # below 1.0800
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert sig.direction.value == "SELL"


# Noise filter

def test_no_signal_range_too_tight():
    # asian_high - asian_low = 1.0803 - 1.0800 = 3 pips < min_range_pips=10
    df = _make_df(last_bar_hour=8, last_close=1.0810,
                  asian_high=1.0803, asian_low=1.0800)
    assert _strat().generate_signal(df, _regime()) is None


# Stop loss placement

def test_stop_loss_at_asian_low_on_buy():
    df = _make_df(last_bar_hour=8, last_close=1.0860)
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert abs(sig.stop_loss - 1.0800) < 1e-6


def test_stop_loss_at_asian_high_on_sell():
    df = _make_df(last_bar_hour=8, last_close=1.0790)
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert abs(sig.stop_loss - 1.0850) < 1e-6


# Take profit

def test_tp_is_range_times_multiplier_on_buy():
    asian_high, asian_low, close = 1.0850, 1.0800, 1.0860
    df = _make_df(last_bar_hour=8, last_close=close,
                  asian_high=asian_high, asian_low=asian_low)
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    expected = close + (asian_high - asian_low) * 1.5
    assert abs(sig.take_profit - expected) < 1e-6


def test_tp_is_range_times_multiplier_on_sell():
    asian_high, asian_low, close = 1.0850, 1.0800, 1.0790
    df = _make_df(last_bar_hour=8, last_close=close,
                  asian_high=asian_high, asian_low=asian_low)
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    expected = close - (asian_high - asian_low) * 1.5
    assert abs(sig.take_profit - expected) < 1e-6


# Meta

def test_strategy_name():
    assert _strat().name == "london_breakout"


def test_jpy_pip_size():
    from src.strategies.london_breakout import _pip_size
    assert _pip_size("USDJPYm") == 0.01
    assert _pip_size("EURUSDm") == 0.0001
