import pytest
from pydantic import ValidationError
from src.config.schema import AppConfig, AccountConfig, RegimeConfig


def test_account_config_defaults():
    cfg = AccountConfig(starting_balance=500)
    assert cfg.max_daily_drawdown_pct == 5
    assert cfg.max_concurrent_positions == 3
    assert cfg.risk_per_trade_pct == 1


def test_account_config_rejects_negative_balance():
    with pytest.raises(ValidationError):
        AccountConfig(starting_balance=-100)


def test_regime_config_defaults():
    cfg = RegimeConfig()
    assert cfg.adx_period == 14
    assert cfg.adx_trend_threshold == 25


def test_app_config_full_construction():
    cfg = AppConfig(account={"starting_balance": 500}, instruments=["EURUSD"])
    assert cfg.account.starting_balance == 500
    assert "EURUSD" in cfg.instruments
    assert cfg.timeframes.regime == "H1"
