import pytest
from pathlib import Path
from src.config.loader import load_config


def test_load_default_config():
    cfg = load_config(Path("config/settings.yaml"))
    assert cfg.account.starting_balance == 1500
    assert "EURUSDm" in cfg.instruments
    assert cfg.regime.adx_period == 14
    assert cfg.regime.adx_trend_threshold == 28
    assert cfg.strategy.mean_reversion.require_double_touch is False
    assert cfg.strategy.momentum.fast_ema == 20


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yaml")
