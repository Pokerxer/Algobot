import pytest
from pydantic import ValidationError
from src.config.schema import AppConfig, AccountConfig, RegimeConfig, MeanReversionStrategyConfig, LondonBreakoutStrategyConfig


def test_account_config_defaults():
    cfg = AccountConfig(starting_balance=500)
    assert cfg.max_daily_drawdown_pct == 5
    assert cfg.max_concurrent_positions == 5
    assert cfg.risk_per_trade_pct == 1


def test_account_config_rejects_negative_balance():
    with pytest.raises(ValidationError):
        AccountConfig(starting_balance=-100)


def test_regime_config_defaults():
    cfg = RegimeConfig()
    assert cfg.adx_period == 14
    assert cfg.adx_trend_threshold == 25


def test_mean_reversion_config_require_divergence_defaults_false():
    cfg = MeanReversionStrategyConfig()
    assert cfg.require_divergence is False


def test_mean_reversion_config_require_divergence_can_be_enabled():
    cfg = MeanReversionStrategyConfig(require_divergence=True)
    assert cfg.require_divergence is True


def test_app_config_full_construction():
    cfg = AppConfig(account={"starting_balance": 500}, instruments=["EURUSD"])
    assert cfg.account.starting_balance == 500
    assert "EURUSD" in cfg.instruments
    assert cfg.timeframes.regime == "H1"


def test_london_breakout_config_defaults():
    cfg = LondonBreakoutStrategyConfig()
    assert cfg.session_start_utc == 7
    assert cfg.session_end_utc == 10
    assert cfg.tp_multiplier == 1.5
    assert cfg.min_range_pips == 10.0
    assert "EURUSDm" in cfg.pairs


def test_strategy_config_has_london_breakout_field():
    from src.config.schema import StrategyConfig
    cfg = StrategyConfig()
    assert hasattr(cfg, "london_breakout")
    assert cfg.london_breakout.session_start_utc == 7
