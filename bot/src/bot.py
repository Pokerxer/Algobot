import logging
from typing import Optional
from src.ai.validator import AIValidator
from src.config.schema import AppConfig
from src.data.cache import OHLCVCache
from src.data.fetcher import DataFetcher
from src.execution.engine import ExecutionEngine
from src.mcp_client.protocol import MCPClient
from src.models.regime import Regime
from src.portfolio.manager import PortfolioManager
from src.regime.detector import RegimeDetector
from src.risk.manager import RiskManager
from src.selection.instrument_selector import InstrumentSelector
from src.strategies.base import BaseStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy

log = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, config: AppConfig, mcp: MCPClient, supabase_logger,
                 ai_validator: Optional[AIValidator] = None):
        self._cfg = config
        self._mcp = mcp
        self._db = supabase_logger
        self._ai = ai_validator
        self._cache = OHLCVCache()
        self._fetcher = DataFetcher(mcp, self._cache)
        self._regime = RegimeDetector(config.regime)
        self._selector = InstrumentSelector(top_n=config.account.max_concurrent_positions)
        self._strategies: dict[Regime, BaseStrategy] = {
            Regime.TRENDING_UP: MomentumStrategy(config.strategy.momentum),
            Regime.TRENDING_DOWN: MomentumStrategy(config.strategy.momentum),
            Regime.RANGING: MeanReversionStrategy(config.strategy.mean_reversion),
        }
        self._risk = RiskManager(config.account)
        self._execution = ExecutionEngine(mcp)
        self._portfolio = PortfolioManager(mcp)
        self._initial_sl: dict[int, float] = {}  # ticket → SL at entry, for R-multiple calcs

    async def run_cycle(self) -> None:
        await self._portfolio.sync()
        await self._manage_stops()
        account = await self._mcp.call_tool("account_info", {})
        balance = float(account.get("balance", self._cfg.account.starting_balance))

        regime_states = []
        for instrument in self._cfg.instruments:
            df = await self._fetcher.fetch_ohlcv(
                instrument, self._cfg.timeframes.regime, bars=500,
            )
            state = self._regime.classify(instrument, df)
            regime_states.append(state)
            self._db.snapshot_regime(state)

        spread_ratios = await self._compute_spread_ratios()
        selected = self._selector.select(
            regime_states, spread_ratios,
            recent_sharpe={i: 1.0 for i in self._cfg.instruments},
        )

        for choice in selected:
            df = await self._fetcher.fetch_ohlcv(
                choice.instrument, self._cfg.timeframes.entry, bars=200,
            )
            state = next(s for s in regime_states if s.instrument == choice.instrument)
            strategy = self._strategies.get(state.regime)
            if strategy is None:
                continue
            signal = strategy.generate_signal(df, state)
            if signal is None:
                continue

            decision = self._risk.evaluate(
                signal=signal, balance=balance,
                open_positions=self._portfolio.positions,
                daily_pnl=self._portfolio.unrealized_pnl(),
                correlation_matrix={},
                spread_ratio=spread_ratios.get(choice.instrument, 1.0),
            )
            if not decision.approved:
                log.info("Signal rejected for %s: %s", choice.instrument, decision.reason)
                self._db.log_signal(signal, executed=False)
                continue

            ai_decision = None
            if self._ai is not None:
                ai_decision = await self._ai.validate(signal, state, balance)
                if ai_decision.action == "VETO":
                    log.info("AI vetoed signal for %s: %s", choice.instrument, ai_decision.reasoning)
                    self._db.log_signal(signal, executed=False,
                                        ai_decision="VETO", ai_reasoning=ai_decision.reasoning)
                    continue
                if ai_decision.action == "MODIFY":
                    if ai_decision.stop_loss is not None:
                        signal = signal.model_copy(update={"stop_loss": ai_decision.stop_loss})
                    if ai_decision.take_profit is not None:
                        signal = signal.model_copy(update={"take_profit": ai_decision.take_profit})
                    log.info("AI modified SL/TP for %s: %s", choice.instrument, ai_decision.reasoning)

            result = await self._execution.place_order(signal, decision.lot_size)
            self._db.log_signal(
                signal, executed=(result.status == "FILLED"),
                ai_decision=ai_decision.action if ai_decision else None,
                ai_reasoning=ai_decision.reasoning if ai_decision else None,
            )
            if result.status == "FILLED" and result.ticket is not None:
                self._initial_sl[result.ticket] = signal.stop_loss
            log.info("Order placed for %s: ticket=%s", choice.instrument, result.ticket)

    async def _manage_stops(self) -> None:
        alive = {p.ticket for p in self._portfolio.positions}
        self._initial_sl = {t: sl for t, sl in self._initial_sl.items() if t in alive}

        for pos in self._portfolio.positions:
            if pos.ticket not in self._initial_sl or pos.current_price is None:
                continue
            initial_sl = self._initial_sl[pos.ticket]
            risk = round(abs(pos.entry_price - initial_sl), 8)
            if risk <= 0:
                continue

            new_sl: float | None = None
            if pos.direction.value == "BUY":
                move = round(pos.current_price - pos.entry_price, 8)
                if move >= 2 * risk:
                    candidate = round(pos.current_price - risk, 5)
                    if pos.stop_loss is None or candidate > pos.stop_loss:
                        new_sl = candidate
                elif move >= risk:
                    if pos.stop_loss is None or pos.stop_loss < pos.entry_price:
                        new_sl = pos.entry_price
            else:
                move = round(pos.entry_price - pos.current_price, 8)
                if move >= 2 * risk:
                    candidate = round(pos.current_price + risk, 5)
                    if pos.stop_loss is None or candidate < pos.stop_loss:
                        new_sl = candidate
                elif move >= risk:
                    if pos.stop_loss is None or pos.stop_loss > pos.entry_price:
                        new_sl = pos.entry_price

            if new_sl is not None:
                await self._execution.modify_position(pos.ticket, stop_loss=new_sl)
                log.info("Stop updated ticket=%s new_sl=%.5f", pos.ticket, new_sl)

    async def _compute_spread_ratios(self) -> dict[str, float]:
        ratios = {}
        for instrument in self._cfg.instruments:
            try:
                info = await self._mcp.call_tool("get_symbol_info", {"symbol": instrument})
                spread = float(info.get("spread", 1.0))
                avg = float(info.get("avg_spread", spread))
                ratios[instrument] = spread / avg if avg > 0 else 1.0
            except Exception:
                ratios[instrument] = 1.0
        return ratios
