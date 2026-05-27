from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
from backtesting.data_provider import CSVDataProvider
from backtesting.metrics import sharpe_ratio, max_drawdown, profit_factor, win_rate
from src.config.schema import AppConfig
from src.models.regime import Regime
from src.regime.detector import RegimeDetector
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy


@dataclass
class BacktestTrade:
    instrument: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    pnl: float
    strategy: str
    regime: str


@dataclass
class BacktestResult:
    final_balance: float
    trades: list[BacktestTrade]
    equity_curve: pd.Series
    metrics: dict[str, float] = field(default_factory=dict)


class BacktestRunner:
    MIN_BARS_FOR_REGIME = 100

    def __init__(self, config: AppConfig, data_provider: CSVDataProvider):
        self._cfg = config
        self._dp = data_provider
        self._regime = RegimeDetector(config.regime)
        self._strategies: dict[Regime, BaseStrategy] = {
            Regime.TRENDING_UP: MomentumStrategy(config.strategy.momentum),
            Regime.TRENDING_DOWN: MomentumStrategy(config.strategy.momentum),
            Regime.RANGING: MeanReversionStrategy(config.strategy.mean_reversion),
        }
        self._risk = RiskManager(config.account)

    def run(self, instrument: str, timeframe: str = "H1",
            start: Optional[str] = None, end: Optional[str] = None) -> BacktestResult:
        df = self._dp.load(instrument, timeframe, start, end)
        balance = self._cfg.account.starting_balance
        trades: list[BacktestTrade] = []
        equity = [balance]
        open_trade: Optional[dict] = None

        for i in range(self.MIN_BARS_FOR_REGIME, len(df)):
            window = df.iloc[: i + 1]
            bar = window.iloc[-1]

            if open_trade is not None:
                pnl = self._update_open_trade(open_trade, bar)
                if pnl is not None:
                    balance += pnl
                    trades.append(BacktestTrade(
                        instrument=instrument,
                        direction=open_trade["direction"],
                        entry_time=open_trade["entry_time"],
                        exit_time=bar.name,
                        entry_price=open_trade["entry_price"],
                        exit_price=open_trade["exit_price"],
                        pnl=pnl,
                        strategy=open_trade["strategy"],
                        regime=open_trade["regime"],
                    ))
                    open_trade = None

            if open_trade is None:
                state = self._regime.classify(instrument, window)
                strategy = self._strategies.get(state.regime)
                if strategy:
                    signal = strategy.generate_signal(window, state)
                    if signal is not None:
                        decision = self._risk.evaluate(
                            signal=signal, balance=balance, open_positions=[],
                            daily_pnl=0, correlation_matrix={}, spread_ratio=0.5,
                        )
                        if decision.approved:
                            open_trade = {
                                "direction": signal.direction.value,
                                "entry_time": bar.name,
                                "entry_price": signal.entry_price,
                                "stop_loss": signal.stop_loss,
                                "take_profit": signal.take_profit,
                                "lot_size": decision.lot_size,
                                "strategy": signal.strategy,
                                "regime": state.regime.value,
                                "exit_price": None,
                            }
            equity.append(balance)

        equity_series = pd.Series(equity)
        pnls = pd.Series([t.pnl for t in trades]) if trades else pd.Series(dtype=float)
        returns = equity_series.pct_change().dropna()

        return BacktestResult(
            final_balance=balance,
            trades=trades,
            equity_curve=equity_series,
            metrics={
                "sharpe": sharpe_ratio(returns),
                "max_drawdown": max_drawdown(equity_series),
                "profit_factor": profit_factor(pnls) if len(pnls) else 0.0,
                "win_rate": win_rate(pnls) if len(pnls) else 0.0,
            },
        )

    @staticmethod
    def _update_open_trade(trade: dict, bar) -> Optional[float]:
        high, low = float(bar["high"]), float(bar["low"])
        sl, tp = trade["stop_loss"], trade["take_profit"]
        entry = trade["entry_price"]
        lot = trade["lot_size"]
        if trade["direction"] == "BUY":
            if low <= sl:
                trade["exit_price"] = sl
                return (sl - entry) * lot * 100000
            if high >= tp:
                trade["exit_price"] = tp
                return (tp - entry) * lot * 100000
        else:
            if high >= sl:
                trade["exit_price"] = sl
                return (entry - sl) * lot * 100000
            if low <= tp:
                trade["exit_price"] = tp
                return (entry - tp) * lot * 100000
        return None
