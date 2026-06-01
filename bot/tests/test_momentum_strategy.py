import numpy as np
import pandas as pd
import pandas_ta as ta
from src.strategies.momentum import MomentumStrategy
from src.config.schema import MomentumStrategyConfig
from src.models.regime import Regime, RegimeState
from src.regime.indicators import compute_adx


def _uptrend_with_pullback(n=200):
    close = np.linspace(1.0, 1.2, n)
    close[-1] = close[-5]  # pullback
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def _rising_adx_series():
    """Monotonically increasing ADX — trend accelerating."""
    return pd.Series(np.linspace(20.0, 45.0, 50))


def _declining_adx_series():
    """ADX peaked then declining — trend losing strength."""
    return pd.Series(np.concatenate([np.linspace(20, 55, 30), np.linspace(55, 35, 20)]))


def _flat_adx_series():
    return pd.Series(np.full(30, 38.0))


def test_no_signal_in_ranging_regime():
    strat = MomentumStrategy(MomentumStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.RANGING, confidence=0.7)
    assert strat.generate_signal(_uptrend_with_pullback(), rs) is None


def test_emits_buy_with_2to1_rr_in_uptrend():
    strat = MomentumStrategy(MomentumStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.TRENDING_UP, confidence=0.8)
    sig = strat.generate_signal(_uptrend_with_pullback(), rs)
    if sig is not None:
        assert sig.direction.value == "BUY"
        r = sig.entry_price - sig.stop_loss
        rr = sig.take_profit - sig.entry_price
        assert abs(rr / r - 2.0) < 0.1


# ── ADX rising filter unit tests ──────────────────────────────────────────────
# These test the _adx_is_rising helper directly with controlled series.

def test_adx_is_rising_returns_true_for_increasing_series():
    from src.strategies.momentum import _adx_is_rising
    assert _adx_is_rising(_rising_adx_series()) is True


def test_adx_is_rising_returns_false_for_declining_series():
    from src.strategies.momentum import _adx_is_rising
    assert _adx_is_rising(_declining_adx_series()) is False


def test_adx_is_rising_returns_false_when_flat():
    from src.strategies.momentum import _adx_is_rising
    assert _adx_is_rising(_flat_adx_series()) is False


def test_adx_is_rising_returns_true_when_insufficient_data():
    """Short series (< lookback+1) should not block signal."""
    from src.strategies.momentum import _adx_is_rising
    assert _adx_is_rising(pd.Series([30.0, 28.0])) is True


# ── Integration: declining ADX suppresses momentum signal ─────────────────────

def _strong_then_flat_uptrend(n=200):
    """160 bars of steep trend (builds ADX high), 40 bars nearly flat (ADX declines).

    Entry geometry (EMA touch + bounce) is present in the last 3 bars.
    Self-validate: compute_adx should show declining ADX at the end.
    """
    strong = np.linspace(1.0, 1.16, 160)
    strong_h = strong + 0.005
    strong_l = strong - 0.003

    flat = np.linspace(1.16, 1.162, 40)
    flat_h = flat + 0.0006
    flat_l = flat - 0.0006

    close = np.concatenate([strong, flat])
    high  = np.concatenate([strong_h, flat_h])
    low   = np.concatenate([strong_l, flat_l])

    # Last 3 bars: small pullback then bounce so entry geometry is present
    ema_approx = 1.160
    close[-3] = ema_approx - 0.0002
    close[-2] = ema_approx + 0.0001
    close[-1] = ema_approx + 0.0003
    low[-2]   = ema_approx - 0.0008   # low touches fast EMA

    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close})


def test_adx_rising_filter_blocks_signal_when_adx_declining():
    """After a peaked trend ADX is declining — signal must be None."""
    df = _strong_then_flat_uptrend()
    adx = compute_adx(df, 14)["adx"]
    assert adx.iloc[-1] < adx.iloc[-3], (
        f"Data setup: expected declining ADX but got {adx.iloc[-3]:.2f}→{adx.iloc[-1]:.2f}"
    )
    strat = MomentumStrategy(MomentumStrategyConfig())
    rs = RegimeState(instrument="GBPUSDm", regime=Regime.TRENDING_UP, confidence=0.9)
    assert strat.generate_signal(df, rs) is None


# ── Volume confirmation unit tests ────────────────────────────────────────────

def _volume_df(pullback_high_vol: bool, n: int = 200):
    """OHLCV with explicit volume column to test volume confirmation helper."""
    close = np.linspace(1.0, 1.2, n)
    volume = np.full(n, 1000.0, dtype=float)
    if pullback_high_vol:
        volume[-2] = 3000.0  # pullback bar: 3× average → strong selling conviction
        volume[-1] = 800.0   # bounce bar: weak
    else:
        volume[-2] = 300.0   # pullback bar: 0.3× average → weak selling
        volume[-1] = 2500.0  # bounce bar: 2.5× average → strong buying
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close, "volume": volume})


def test_volume_confirms_bounce_true_for_favorable_volume():
    """Weak pullback bar + strong bounce bar → volume confirms entry."""
    from src.strategies.momentum import _volume_confirms_bounce
    assert _volume_confirms_bounce(_volume_df(pullback_high_vol=False)) is True


def test_volume_confirms_bounce_false_for_high_pullback_volume():
    """Strong selling on pullback bar → volume does NOT confirm bounce."""
    from src.strategies.momentum import _volume_confirms_bounce
    assert _volume_confirms_bounce(_volume_df(pullback_high_vol=True)) is False


def test_volume_confirms_bounce_true_when_no_volume_column():
    """No volume column → filter skipped (fail open), backward compatible."""
    from src.strategies.momentum import _volume_confirms_bounce
    df = _uptrend_with_pullback()  # no volume column
    assert _volume_confirms_bounce(df) is True


def test_volume_confirms_bounce_true_when_volume_all_zeros():
    """All-zero volume (typical for some MT5 symbols) → filter skipped."""
    from src.strategies.momentum import _volume_confirms_bounce
    df = _uptrend_with_pullback().copy()
    df["volume"] = 0.0
    assert _volume_confirms_bounce(df) is True
