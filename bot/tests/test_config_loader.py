import pytest
from pathlib import Path
from src.config.loader import load_config


def test_load_default_config():
    cfg = load_config(Path("config/settings.yaml"))
    assert cfg.account.starting_balance == 500
    assert "EURUSD" in cfg.instruments
    assert cfg.regime.adx_period == 14
    assert cfg.strategy.momentum.fast_ema == 20


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yaml")
