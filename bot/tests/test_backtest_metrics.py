import pandas as pd
from backtesting.metrics import sharpe_ratio, max_drawdown, profit_factor, win_rate


def test_sharpe_zero_for_zero_variance():
    assert sharpe_ratio(pd.Series([0, 0, 0, 0])) == 0


def test_sharpe_positive_for_positive_returns():
    assert sharpe_ratio(pd.Series([0.01, 0.02, 0.01, 0.015])) > 0


def test_max_drawdown_simple_case():
    equity = pd.Series([100, 110, 105, 90, 95, 120])
    assert abs(max_drawdown(equity) - 0.1818) < 0.01


def test_profit_factor():
    assert abs(profit_factor(pd.Series([10, -5, 8, -3, 12])) - 3.75) < 0.01


def test_profit_factor_no_losses():
    assert profit_factor(pd.Series([10, 5, 8])) == float("inf")


def test_win_rate():
    assert win_rate(pd.Series([10, -5, 8, -3, 12])) == 0.6
