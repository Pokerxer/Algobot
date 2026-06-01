import numpy as np
import pandas as pd
import pytest

from src.config.schema import AppConfig
from src.insight.evaluator import Evaluation, evaluate
from src.models.regime import Regime, RegimeState
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy


def _cfg() -> AppConfig:
    return AppConfig(account={"starting_balance": 500}, instruments=["EURUSD"])


def _walk_df(n=200, price=1.10, seed=7):
    # Mild random walk → valid (non-NaN) indicators and non-degenerate bands,
    # so the evaluator exercises the full breakdown path. (A perfectly flat df
    # gives NaN RSI / collapsed bands and must NOT be used here.)
    rng = np.random.default_rng(seed)
    close = price + np.cumsum(rng.normal(0, 0.0004, n))
    return pd.DataFrame({"open": close, "high": close + 0.0003,
                         "low": close - 0.0003, "close": close,
                         "volume": np.full(n, 1000.0)})


def _state(regime, inst="EURUSD"):
    return RegimeState(instrument=inst, regime=regime, confidence=0.5)


def test_gated_when_out_of_session():
    ev = evaluate("EURUSD", _state(Regime.RANGING), _walk_df(), _cfg(),
                  MeanReversionStrategy(_cfg().strategy.mean_reversion),
                  in_session=False, allowed_regimes=None, mtf_aligned=None,
                  is_mean_rev_only=False, is_momentum_only=False)
    assert ev.status == "gated"
    assert ev.strategy is None
    assert ev.setup_distance is None
    assert "session" in ev.reason.lower()


def test_gated_by_session_regime():
    ev = evaluate("US500m", _state(Regime.CHOPPY, "US500m"), _walk_df(), _cfg(),
                  MeanReversionStrategy(_cfg().strategy.mean_reversion),
                  in_session=True, allowed_regimes=frozenset({Regime.RANGING}),
                  mtf_aligned=None, is_mean_rev_only=False, is_momentum_only=False)
    assert ev.status == "gated"
    assert "session-regime" in ev.reason.lower()


def test_mean_reversion_status_matches_strategy_and_builds_detail():
    # status MUST equal the real strategy verdict (cannot drift); the breakdown
    # is populated regardless of which way the verdict goes.
    strat = MeanReversionStrategy(_cfg().strategy.mean_reversion)
    df, st = _walk_df(), _state(Regime.RANGING)
    ev = evaluate("EURUSD", st, df, _cfg(), strat,
                  in_session=True, allowed_regimes=None, mtf_aligned=None,
                  is_mean_rev_only=False, is_momentum_only=False)
    real = strat.generate_signal(df, st)
    assert (ev.status == "signal") == (real is not None)
    assert ev.strategy == "mean_reversion"
    assert "pct_b" in ev.detail
    assert 0.0 <= ev.setup_distance <= 1.0
    assert ev.reason


def test_momentum_status_matches_strategy_and_builds_detail():
    strat = MomentumStrategy(_cfg().strategy.momentum)
    df, st = _walk_df(seed=3), _state(Regime.TRENDING_DOWN)
    ev = evaluate("BTCUSDm", st, df, _cfg(), strat,
                  in_session=True, allowed_regimes=None, mtf_aligned=True,
                  is_mean_rev_only=False, is_momentum_only=False)
    real = strat.generate_signal(df, st)
    assert (ev.status == "signal") == (real is not None)
    assert "adx_rising" in ev.detail
    assert 0.0 <= ev.setup_distance <= 1.0
