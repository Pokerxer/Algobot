from pathlib import Path
from backtesting.runner import BacktestRunner, BacktestResult
from backtesting.data_provider import CSVDataProvider
from src.config.schema import AppConfig


def test_backtest_runs_end_to_end():
    cfg = AppConfig(account={"starting_balance": 10000}, instruments=["EURUSD"])
    runner = BacktestRunner(cfg, CSVDataProvider(Path("tests/fixtures")))
    result = runner.run(instrument="EURUSD", timeframe="H1")
    assert isinstance(result, BacktestResult)
    assert result.final_balance > 0
    assert "sharpe" in result.metrics
    assert "max_drawdown" in result.metrics
    assert "profit_factor" in result.metrics
    assert "win_rate" in result.metrics


def test_backtest_with_no_signals():
    cfg = AppConfig(
        account={"starting_balance": 1000}, instruments=["EURUSD"],
        # choch_supplement disabled so the extreme ADX thresholds actually force
        # everything to RANGING and prevent any signals from firing
        regime={"adx_trend_threshold": 100, "adx_range_threshold": 0, "choch_supplement": False},
    )
    result = BacktestRunner(cfg, CSVDataProvider(Path("tests/fixtures"))).run(
        instrument="EURUSD", timeframe="H1",
    )
    assert result.final_balance == 1000
    assert len(result.trades) == 0
