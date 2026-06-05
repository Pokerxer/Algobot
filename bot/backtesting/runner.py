from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import pandas_ta as ta

from backtesting.data_provider import CSVDataProvider
from backtesting.metrics import sharpe_ratio, max_drawdown, profit_factor, win_rate
from src.config.schema import AppConfig
from src.models.regime import Regime
from src.regime.detector import RegimeDetector
from src.risk.manager import RiskManager, _pip_spec
from src.strategies.base import BaseStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy
from src.strategies.smc_gold import SMCGoldStrategy
from src.bot import _MEAN_REV_ONLY, _MOMENTUM_ONLY, _LONG_BIAS, _SMC_INSTRUMENTS


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
    D1_EMA_PERIOD = 50

    def __init__(self, config: AppConfig, data_provider: CSVDataProvider):
        self._cfg = config
        self._dp = data_provider
        self._regime = RegimeDetector(config.regime)
        self._smc_gold = SMCGoldStrategy()
        self._strategies: dict[Regime, BaseStrategy] = {
            Regime.TRENDING_UP:   MomentumStrategy(config.strategy.momentum),
            Regime.TRENDING_DOWN: MomentumStrategy(config.strategy.momentum),
            Regime.RANGING:       MeanReversionStrategy(config.strategy.mean_reversion),
            Regime.CHOPPY:        MeanReversionStrategy(config.strategy.mean_reversion),
        }
        self._risk = RiskManager(config.account)

    # ── Kill zone check using bar timestamp (not live clock) ─────────────────

    _KILL_ZONES: list[tuple[int, int]] = [(7, 10), (12, 16)]  # London open, NY open extended

    @classmethod
    def _in_kill_zone_at(cls, bar_time: pd.Timestamp) -> bool:
        """Return True if the bar's UTC hour falls within a kill zone."""
        hour = bar_time.tz_convert("UTC").hour if bar_time.tzinfo else bar_time.hour
        return any(start <= hour < end for start, end in cls._KILL_ZONES)

    # ── D1 alignment (Fix 1) ──────────────────────────────────────────────────

    @staticmethod
    def _d1_aligned(h1_window: pd.DataFrame, direction: str) -> bool:
        """Return True if the daily (D1) 50-EMA trend matches `direction`.

        Resamples H1 data to D1 so the backtest mirrors the live bot's D1 check.
        Fails open (True) when there's insufficient data for the EMA.
        """
        try:
            d1 = h1_window.resample("1D").agg(
                open=("open", "first"), high=("high", "max"),
                low=("low", "min"), close=("close", "last"),
            ).dropna()
            if len(d1) < BacktestRunner.D1_EMA_PERIOD + 5:
                return True   # not enough history — fail open
            ema = ta.ema(d1["close"], length=BacktestRunner.D1_EMA_PERIOD)
            if ema is None or pd.isna(ema.iloc[-1]):
                return True
            last_close = float(d1["close"].iloc[-1])
            last_ema   = float(ema.iloc[-1])
            if direction == "BUY":
                return last_close > last_ema
            else:
                return last_close < last_ema
        except Exception:
            return True   # fail open

    # ── main backtest loop ────────────────────────────────────────────────────

    def run(self, instrument: str, timeframe: str = "H1",
            start: Optional[str] = None, end: Optional[str] = None) -> BacktestResult:

        # Load H1 for regime detection and D1 alignment
        h1 = self._dp.load(instrument, "H1", start, end)

        # Load M15 for entry signal generation if available, else fall back to H1
        try:
            m15 = self._dp.load(instrument, "M15", start, end)
            use_m15 = True
        except (FileNotFoundError, KeyError):
            m15 = h1
            use_m15 = False

        balance = self._cfg.account.starting_balance
        trades: list[BacktestTrade] = []
        equity = [balance]
        open_trade: Optional[dict] = None

        # Live-bot state tracking
        sl_cooldown: dict[str, pd.Timestamp] = {}      # loss cooldown per instrument
        COOLDOWN_HOURS = 1                              # 60-min block after SL hit
        day_start_balance = balance                     # for daily drawdown check
        current_day: Optional[pd.Timestamp] = None

        for i in range(self.MIN_BARS_FOR_REGIME, len(h1)):
            h1_window = h1.iloc[: i + 1]
            bar = h1_window.iloc[-1]
            bar_time = h1_window.index[-1]

            # ── daily drawdown reset and halt ──
            bar_day = bar_time.normalize()
            if current_day != bar_day:
                current_day = bar_day
                day_start_balance = balance
            daily_pnl = balance - day_start_balance
            max_dd = day_start_balance * (self._cfg.account.max_daily_drawdown_pct / 100)
            if daily_pnl <= -max_dd and open_trade is None:
                equity.append(balance)
                continue   # daily drawdown limit hit — no new entries today

            # ── manage open trade ──
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
                    # Record SL hit for cooldown (loss = SL hit in this model)
                    if pnl < 0:
                        sl_cooldown[instrument] = bar_time
                    open_trade = None

            if open_trade is None:
                # ── loss cooldown check (mirrors A in run_cycle) ──
                if instrument in sl_cooldown:
                    hours_since = (bar_time - sl_cooldown[instrument]).total_seconds() / 3600
                    if hours_since < COOLDOWN_HOURS:
                        equity.append(balance)
                        continue

                # ── SMC instrument pass (mirrors bot.py _SMC_INSTRUMENTS) ──
                if instrument in _SMC_INSTRUMENTS:
                    if use_m15:
                        smc_window = m15[m15.index <= bar_time].tail(200)
                        if len(smc_window) < 50:
                            equity.append(balance)
                            continue
                    else:
                        smc_window = h1_window
                    from src.models.regime import RegimeState
                    smc_state = RegimeState(instrument=instrument,
                                           regime=Regime.RANGING, confidence=0.5)
                    # in_kill_zone uses live time — patch with bar time for backtest
                    import unittest.mock as _mock
                    _bar_hour = bar_time.tz_convert("UTC").hour
                    _in_kz = any(s <= _bar_hour < e for s, e in [(7, 10), (12, 16)])
                    with _mock.patch("src.strategies.smc_gold.in_kill_zone",
                                     return_value=_in_kz):
                        signal = self._smc_gold.generate_signal(smc_window, smc_state)
                    if signal is not None:
                        decision = self._risk.evaluate(
                            signal=signal, balance=balance, open_positions=[],
                            daily_pnl=daily_pnl, correlation_matrix={}, spread_ratio=0.5,
                        )
                        if decision.approved:
                            open_trade = {
                                "instrument": instrument,
                                "direction": signal.direction.value,
                                "entry_time": bar.name,
                                "entry_price": signal.entry_price,
                                "stop_loss": signal.stop_loss,
                                "take_profit": signal.take_profit,
                                "lot_size": decision.lot_size,
                                "strategy": signal.strategy,
                                "regime": "smc_gold",
                                "exit_price": None,
                            }
                    equity.append(balance)
                    continue

                # ── classify regime from H1 ──
                state = self._regime.classify(instrument, h1_window)

                # ── mandate check: mirrors _mandate_blocks() in TradingBot ──
                # EURUSDm = mean-rev only; GBPJPYm/USTECm/BTC/ETH = momentum only
                if instrument in _MEAN_REV_ONLY and state.regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
                    equity.append(balance)
                    continue
                if instrument in _MOMENTUM_ONLY and state.regime in (Regime.RANGING, Regime.CHOPPY):
                    equity.append(balance)
                    continue

                strategy = self._strategies.get(state.regime)
                if not strategy:
                    equity.append(balance)
                    continue

                # ── Fix 1: D1 alignment + kill zone + long-bias check for momentum ──
                if state.regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
                    direction = "BUY" if state.regime == Regime.TRENDING_UP else "SELL"
                    if not self._d1_aligned(h1_window, direction):
                        equity.append(balance)
                        continue
                    # Kill zone filter
                    if not self._in_kill_zone_at(bar_time):
                        equity.append(balance)
                        continue
                    # Long-bias block: no momentum SELL on precious metals
                    if instrument in _LONG_BIAS and state.regime == Regime.TRENDING_DOWN:
                        equity.append(balance)
                        continue

                # ── Fix 2: use M15 window for entry signal generation ──
                if use_m15:
                    entry_window = m15[m15.index <= bar_time].tail(200)
                    if len(entry_window) < 50:
                        equity.append(balance)
                        continue
                else:
                    entry_window = h1_window

                signal = strategy.generate_signal(entry_window, state)
                if signal is not None:
                    decision = self._risk.evaluate(
                        signal=signal, balance=balance, open_positions=[],
                        daily_pnl=daily_pnl, correlation_matrix={}, spread_ratio=0.5,
                    )
                    if decision.approved:
                        open_trade = {
                            "instrument": instrument,
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
                "sharpe":       sharpe_ratio(returns),
                "max_drawdown": max_drawdown(equity_series),
                "profit_factor": profit_factor(pnls) if len(pnls) else 0.0,
                "win_rate":     win_rate(pnls) if len(pnls) else 0.0,
            },
        )

    @staticmethod
    def _update_open_trade(trade: dict, bar) -> Optional[float]:
        high, low = float(bar["high"]), float(bar["low"])
        sl, tp = trade["stop_loss"], trade["take_profit"]
        entry = trade["entry_price"]
        lot = trade["lot_size"]
        pip_size, pip_value = _pip_spec(trade["instrument"])

        def pnl(exit_price: float, direction: str) -> float:
            move = exit_price - entry if direction == "BUY" else entry - exit_price
            return (move / pip_size) * pip_value * lot

        if trade["direction"] == "BUY":
            if low <= sl:
                trade["exit_price"] = sl
                return pnl(sl, "BUY")
            if high >= tp:
                trade["exit_price"] = tp
                return pnl(tp, "BUY")
        else:
            if high >= sl:
                trade["exit_price"] = sl
                return pnl(sl, "SELL")
            if low <= tp:
                trade["exit_price"] = tp
                return pnl(tp, "SELL")
        return None
