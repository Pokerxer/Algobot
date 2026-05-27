import logging
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
    def __init__(self, config: AppConfig, mcp: MCPClient, supabase_logger):
        self._cfg = config
        self._mcp = mcp
        self._db = supabase_logger
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

    async def run_cycle(self) -> None:
        await self._portfolio.sync()
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

            result = await self._execution.place_order(signal, decision.lot_size)
            self._db.log_signal(signal, executed=(result.status == "FILLED"))
            log.info("Order placed for %s: ticket=%s", choice.instrument, result.ticket)

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
