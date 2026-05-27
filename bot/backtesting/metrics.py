import numpy as np
import pandas as pd


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    if returns.std() == 0 or len(returns) == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * returns.mean() / returns.std())


def max_drawdown(equity: pd.Series) -> float:
    if len(equity) == 0:
        return 0.0
    running_max = equity.cummax()
    drawdowns = (running_max - equity) / running_max
    return float(drawdowns.max())


def profit_factor(pnls: pd.Series) -> float:
    gross_profit = pnls[pnls > 0].sum()
    gross_loss = abs(pnls[pnls < 0].sum())
    if gross_loss == 0:
        return float("inf")
    return float(gross_profit / gross_loss)


def win_rate(pnls: pd.Series) -> float:
    if len(pnls) == 0:
        return 0.0
    return float((pnls > 0).sum() / len(pnls))
