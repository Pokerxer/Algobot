import numpy as np
import pandas as pd
import pandas_ta as ta
from src.strategies.mean_reversion import MeanReversionStrategy
from src.config.schema import MeanReversionStrategyConfig
from src.models.regime import Regime, RegimeState


def _ranging_with_dip(n=200):
    rng = np.random.default_rng(7)
    close = 1.0 + 0.005 * np.sin(np.linspace(0, 20, n)) + rng.normal(0, 0.0002, n)
    close[-10:] = np.linspace(close[-11], close[-11] - 0.02, 10)
    return pd.DataFrame({"open": close, "high": close + 0.0005,
                         "low": close - 0.0005, "close": close})


def _build_rsi_divergence_df(divergence: bool, n: int = 200):
    """Two tiny lower-BB touches at bars -3 and -1 (within lookback=12).

    The stable base (std ≈ 0.0001) keeps BB narrow, so small dips breach it
    without widening it enough to swallow the second touch.

    DIVERGENCE=True  : bar -3 drops -0.002 (RSI ~28), bar -2 recovers +0.001,
                       bar -1 drops -0.001 (RSI ~35 > 28 = divergence)
    DIVERGENCE=False : bar -3 drops -0.002 (RSI ~28), bar -2 stable,
                       bar -1 drops -0.003 (RSI ~16 < 28 = no divergence)
    """
    # Stable base at 1.010 — keeps stable lows (~1.0097) above BB-lower*1.002 (~1.004),
    # so only the genuine dip bars are found as prior touches by _prior_touch_idx.
    rng = np.random.default_rng(99)
    close = np.empty(n)
    close[:n - 3] = 1.010 + rng.normal(0, 0.0001, n - 3)

    if divergence:
        close[n - 3] = 0.998   # first touch: big -12 pip drop, RSI very low (~10)
        close[n - 2] = 0.999   # slight recovery
        close[n - 1] = 0.998   # second touch: same level, RSI higher (~15 > 10)
    else:
        close[n - 3] = 0.998   # first touch: big -12 pip drop, RSI very low (~10)
        close[n - 2] = 0.998   # stays low (no recovery)
        close[n - 1] = 0.995   # second touch: bigger drop, RSI even lower (~8 < 10)

    high = close + 0.0003
    low  = close - 0.0003
    low[n - 3] -= 0.001   # ensure first touch low clearly breaches BB lower
    low[n - 1] -= 0.001   # ensure second touch low clearly breaches BB lower

    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close})


def _rsi_at_bar(df, bar_idx):
    rsi = ta.rsi(df["close"], length=14)
    return float(rsi.iloc[bar_idx])


def _bb_lower_at_bar(df, bar_idx):
    bb = ta.bbands(df["close"], length=20, std=2.0)
    col = next(c for c in bb.columns if c.startswith("BBL"))
    return float(bb[col].iloc[bar_idx])


def test_skips_trending_regime():
    strat = MeanReversionStrategy(MeanReversionStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.TRENDING_UP, confidence=0.8)
    assert strat.generate_signal(_ranging_with_dip(), rs) is None


def test_fires_in_choppy_regime():
    """CHOPPY (ADX 20-33) should also allow mean reversion — EURUSD Asian session."""
    strat = MeanReversionStrategy(MeanReversionStrategyConfig())
    rs = RegimeState(instrument="EURUSDm", regime=Regime.CHOPPY, confidence=0.5)
    sig = strat.generate_signal(_ranging_with_dip(), rs)
    assert sig is not None
    assert sig.direction.value == "BUY"


def test_buys_on_oversold_lower_band():
    strat = MeanReversionStrategy(MeanReversionStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.RANGING, confidence=0.7)
    df = _ranging_with_dip()
    sig = strat.generate_signal(df, rs)
    assert sig is not None
    assert sig.direction.value == "BUY"
    # Stop below entry, TP (middle band) above entry
    assert sig.stop_loss < sig.entry_price
    assert sig.take_profit > sig.entry_price


# ── Divergence unit tests ─────────────────────────────────────────────────────

def test_rsi_diverges_bullish_true_when_rsi_recovers():
    from src.strategies.mean_reversion import _rsi_diverges_bullish
    rsi = pd.Series(np.concatenate([np.full(14, 50.0), [18.0], np.full(8, 50.0), [28.0]]))
    # prior_rsi at index -10 = 18, current rsi at index -1 = 28 → divergence
    assert _rsi_diverges_bullish(rsi, prior_idx=-10) is True


def test_rsi_diverges_bullish_false_when_rsi_worsens():
    from src.strategies.mean_reversion import _rsi_diverges_bullish
    rsi = pd.Series(np.concatenate([np.full(14, 50.0), [28.0], np.full(8, 50.0), [18.0]]))
    # prior_rsi = 28, current = 18 → no divergence
    assert _rsi_diverges_bullish(rsi, prior_idx=-10) is False


def test_rsi_diverges_bullish_false_when_rsi_equal():
    from src.strategies.mean_reversion import _rsi_diverges_bullish
    rsi = pd.Series(np.concatenate([np.full(14, 50.0), [25.0], np.full(8, 50.0), [25.0]]))
    assert _rsi_diverges_bullish(rsi, prior_idx=-10) is False


# ── Integration: require_divergence config flag ───────────────────────────────

def test_divergence_blocks_signal_when_rsi_continues_falling():
    """require_divergence=True: no signal when RSI is lower at second touch."""
    df = _build_rsi_divergence_df(divergence=False)

    # Self-validate: bar -3 (first touch) should have higher RSI than bar -1 (second)
    first_rsi  = _rsi_at_bar(df, -3)
    second_rsi = _rsi_at_bar(df, -1)
    assert second_rsi < first_rsi, (
        f"Data setup: expected RSI to fall at 2nd touch ({first_rsi:.1f}→{second_rsi:.1f})"
    )

    cfg = MeanReversionStrategyConfig(
        rsi_oversold=40,
        require_double_touch=True,
        require_divergence=True,
        bb_expansion_filter=False,
    )
    strat = MeanReversionStrategy(cfg)
    rs = RegimeState(instrument="EURUSDm", regime=Regime.RANGING, confidence=0.8)
    assert strat.generate_signal(df, rs) is None


def test_divergence_allows_signal_when_rsi_recovers():
    """require_divergence=True: signal fires when RSI is higher at second touch."""
    df = _build_rsi_divergence_df(divergence=True)

    # Self-validate: bar -3 (first touch) should have lower RSI than bar -1 (second)
    first_rsi  = _rsi_at_bar(df, -3)
    second_rsi = _rsi_at_bar(df, -1)
    assert second_rsi > first_rsi, (
        f"Data setup: expected RSI divergence ({first_rsi:.1f}→{second_rsi:.1f})"
    )

    cfg = MeanReversionStrategyConfig(
        rsi_oversold=40,
        require_double_touch=True,
        require_divergence=True,
        bb_expansion_filter=False,
    )
    strat = MeanReversionStrategy(cfg)
    rs = RegimeState(instrument="EURUSDm", regime=Regime.RANGING, confidence=0.8)
    sig = strat.generate_signal(df, rs)
    assert sig is not None
    assert sig.direction.value == "BUY"


# ── middle-band take-profit target ───────────────────────────────────────────

def test_buy_take_profit_at_middle_band():
    """BUY TP targets the middle band (full mean reversion), giving R/R > 1:1."""
    strat = MeanReversionStrategy(MeanReversionStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.RANGING, confidence=0.7)
    df = _ranging_with_dip()
    sig = strat.generate_signal(df, rs)
    assert sig is not None
    assert sig.direction.value == "BUY"

    bb = ta.bbands(df["close"], length=20, std=2.0)
    m_col = next(c for c in bb.columns if c.startswith("BBM"))
    middle = float(bb[m_col].iloc[-1])
    assert abs(sig.take_profit - middle) < 1e-6


def test_sell_take_profit_at_middle_band():
    """SELL TP targets the middle band (full mean reversion), giving R/R > 1:1."""
    rng = np.random.default_rng(42)
    n = 200
    close = 1.0 + 0.005 * np.sin(np.linspace(0, 20, n)) + rng.normal(0, 0.0002, n)
    close[-10:] = np.linspace(close[-11], close[-11] + 0.02, 10)  # spike up
    df = pd.DataFrame({"open": close, "high": close + 0.0005,
                       "low": close - 0.0005, "close": close})

    strat = MeanReversionStrategy(MeanReversionStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.RANGING, confidence=0.7)
    sig = strat.generate_signal(df, rs)
    assert sig is not None
    assert sig.direction.value == "SELL"

    bb = ta.bbands(df["close"], length=20, std=2.0)
    m_col = next(c for c in bb.columns if c.startswith("BBM"))
    middle = float(bb[m_col].iloc[-1])
    assert abs(sig.take_profit - middle) < 1e-6
