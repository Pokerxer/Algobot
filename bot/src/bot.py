import io
import logging
from datetime import date, datetime, timezone
from typing import Optional

def _crumb(msg):
    from pathlib import Path
    with open(Path(__file__).parent.parent.parent / "crumb.log", "a") as f:
        import datetime as _dt
        f.write(f"{_dt.datetime.now().isoformat()} BOT:{msg}\n")

_crumb("START")
import pandas as pd
_crumb("PANDAS")
import pandas_ta as ta
_crumb("PANDAS_TA")

from src.ai.validator import AIValidator
_crumb("AI_VALIDATOR")
from src.config.schema import AppConfig
from src.data.cache import OHLCVCache
from src.data.fetcher import DataFetcher
from src.execution.engine import ExecutionEngine
from src.mcp_client.protocol import MCPClient
from src.models.position import Position
from src.models.regime import Regime, RegimeState
from src.portfolio.manager import PortfolioManager
from src.regime.detector import RegimeDetector
from src.regime.indicators import compute_atr
from src.risk.manager import RiskManager
from src.selection.instrument_selector import InstrumentSelector
from src.indicators.order_blocks import in_kill_zone
from src.insight.evaluator import evaluate
from src.strategies.base import BaseStrategy
_crumb("SRC_IMPORTS")
from src.strategies.london_breakout import LondonBreakoutStrategy
_crumb("LONDON_BREAKOUT")
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy
_crumb("ALL_STRATEGIES")

log = logging.getLogger(__name__)

# EURUSDm is a ranging instrument — only trade mean reversion, never momentum
_MEAN_REV_ONLY: frozenset[str] = frozenset({"EURUSDm"})

# Momentum-only pairs — too volatile or gap-prone for reliable MR band-touch entries
# GBPJPYm: 200+ pip daily range, MR stops blow out on normal noise
# USTECm/BTC/ETH: gap and spike risk makes MR unreliable
_MOMENTUM_ONLY: frozenset[str] = frozenset({"GBPJPYm", "USTECm", "BTCUSDm", "ETHUSDm"})


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
            Regime.TRENDING_UP:   MomentumStrategy(config.strategy.momentum),
            Regime.TRENDING_DOWN: MomentumStrategy(config.strategy.momentum),
            Regime.RANGING:       MeanReversionStrategy(config.strategy.mean_reversion),
            Regime.CHOPPY:        MeanReversionStrategy(config.strategy.mean_reversion),
        }
        self._parallel_strategies: list[BaseStrategy] = [
            LondonBreakoutStrategy(config.strategy.london_breakout),
        ]
        self._risk = RiskManager(config.account)
        self._execution = ExecutionEngine(mcp)
        self._portfolio = PortfolioManager(mcp)

        # Live balance cache — updated each cycle, used as fallback on MCP failure
        self._last_balance: float = config.account.starting_balance

        # Closed-trade detection
        self._open_tickets: dict[int, Position] = {}

        # Daily realized P&L
        self._realized_pnl_today: float = 0.0
        self._pnl_date: date = date.today()

        # Spread EMA per instrument (alpha ≈ 0.05 → ~20-period)
        self._spread_ema: dict[str, float] = {}

        # Tickets we've already attempted a time-based close on this session.
        # Prevents hammering MT5 with close calls every cycle when the market is
        # closed (e.g. after 21:00 UTC for US indices) or when the close fails silently.
        self._close_attempted: set[int] = set()

        # Last signal time per (instrument, direction) — dedup guard.
        self._last_signal_time: dict[tuple[str, str], datetime] = {}
        self._signal_dedup_seconds: int = 300   # 5-minute window

        # A: Loss cooldown — after an SL hit, block that instrument for 60 min.
        # Prevents re-entering at the same invalidated level immediately.
        self._sl_cooldown: dict[str, datetime] = {}
        self._sl_cooldown_minutes: int = 60

        # C: Max 2 same-direction losses per instrument per day.
        # After losing twice on the same side, the market has rejected that setup — stop.
        self._daily_sl_counts: dict[tuple[str, str], int] = {}
        self._daily_sl_date: date = date.today()

    # ── main loop ────────────────────────────────────────────────────────────

    async def run_cycle(self) -> None:
        await self._portfolio.sync()
        account = await self._mcp.call_tool("account_info", {})
        balance = float(account.get("balance", self._last_balance))
        equity  = float(account.get("equity",  balance))
        self._last_balance = balance  # always cache the latest

        # Classify regimes — pure computation, no Supabase writes yet.
        # All DB writes are deferred until after signals are evaluated and orders placed,
        # so Supabase network issues can never block trade execution.
        regime_states: list[RegimeState] = []
        for instrument in self._cfg.instruments:
            df = await self._fetcher.fetch_ohlcv(
                instrument, self._cfg.timeframes.regime, bars=500,
            )
            state = self._regime.classify(instrument, df)
            regime_states.append(state)

        # Detect positions closed by MT5 (SL/TP hit) → write to trades table
        await self._detect_closed_trades()

        # Trailing stops + time-based exit + live price sync + DB upsert
        await self._manage_positions()

        # Correlation matrix from cached H1 closes
        corr_matrix = self._compute_correlation_matrix()

        # Spread ratios with rolling EMA baseline
        spread_ratios = await self._compute_spread_ratios()

        # Instrument selection with Sharpe from trade history
        selected = self._selector.select(
            regime_states, spread_ratios,
            recent_sharpe=self._compute_sharpe_by_instrument(),
        )

        # Signal evaluation and order placement
        for choice in selected:
            # Session filter — skip instruments outside their high-liquidity window
            if not self._in_session(choice.instrument):
                log.debug("Out of session: %s", choice.instrument)
                continue

            df = await self._fetcher.fetch_ohlcv(
                choice.instrument, self._cfg.timeframes.entry, bars=200,
            )
            state = next(s for s in regime_states if s.instrument == choice.instrument)

            # Instrument routing: mean-reversion-only pairs (e.g. EURUSD) skip
            # trending regimes; momentum-only high-ADR pairs skip ranging AND
            # choppy regimes (both route to mean reversion). See _mandate_blocks.
            if self._mandate_blocks(choice.instrument, state.regime):
                continue

            # Split-session routing: XAUUSDm and US500m use different strategies
            # depending on the current UTC session (Asian vs London/NY, pre-market vs NYSE)
            allowed_regimes = self._session_allowed_regimes(choice.instrument)
            if allowed_regimes is not None and state.regime not in allowed_regimes:
                log.debug(
                    "Session regime gate: %s regime=%s not allowed at this hour",
                    choice.instrument, state.regime.name,
                )
                continue

            # Multi-timeframe direction filter for momentum signals.
            # H1 + H4 + D1 all aligned lifts win rate from ~55% to ~65%.
            if state.regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
                direction = "BUY" if state.regime == Regime.TRENDING_UP else "SELL"
                if not await self._h4_aligned(choice.instrument, direction):
                    log.debug("H4 not aligned: %s %s", choice.instrument, direction)
                    continue
                if not await self._d1_aligned(choice.instrument, direction):
                    log.debug("D1 not aligned: %s %s", choice.instrument, direction)
                    continue

                # Kill zone filter: momentum entries only during London open (07-10 UTC)
                # or NY open (12-15 UTC). Backtesting showed momentum win rate drops to
                # 25% outside kill zones vs 40%+ inside — noise trades dominate.
                if not in_kill_zone():
                    log.debug("Momentum outside kill zone — skipping: %s", choice.instrument)
                    continue

            strategy = self._strategies.get(state.regime)
            if strategy is None:
                continue
            signal = strategy.generate_signal(df, state)
            if signal is None:
                continue

            # A: Loss cooldown — skip instrument for 60 min after an SL hit.
            cooldown_since = self._sl_cooldown.get(choice.instrument)
            if cooldown_since is not None:
                elapsed_min = (datetime.now(timezone.utc) - cooldown_since).total_seconds() / 60
                if elapsed_min < self._sl_cooldown_minutes:
                    log.info(
                        "Cooldown: skipping %s (%.0f min remaining after SL)",
                        choice.instrument, self._sl_cooldown_minutes - elapsed_min,
                    )
                    self._db.log_signal(signal, executed=False,
                                        rejection_reason=f"loss cooldown ({self._sl_cooldown_minutes - elapsed_min:.0f} min remaining)")
                    continue

            # B: H4 trend filter for mean-reversion — don't enter MR against a strong H4 trend.
            # XAU/USDJPY losses: bot bought/sold into structural H4 trends and got stopped.
            if state.regime in (Regime.RANGING, Regime.CHOPPY):
                opposing = "SELL" if signal.direction.value == "BUY" else "BUY"
                if await self._h4_aligned(choice.instrument, opposing):
                    log.info(
                        "MR %s skipped: H4 trending against on %s",
                        signal.direction.value, choice.instrument,
                    )
                    self._db.log_signal(signal, executed=False,
                                        rejection_reason=f"H4 trending against MR {signal.direction.value}")
                    continue

            # C: Max 2 same-direction losses per instrument per day.
            today = datetime.now(timezone.utc).date()
            if today != self._daily_sl_date:
                self._daily_sl_counts.clear()
                self._daily_sl_date = today
            loss_key = (signal.instrument, signal.direction.value)
            if self._daily_sl_counts.get(loss_key, 0) >= 2:
                log.info(
                    "Max daily losses reached for %s %s — skipping",
                    signal.instrument, signal.direction.value,
                )
                self._db.log_signal(signal, executed=False,
                                    rejection_reason=f"max daily SL ({signal.direction.value}) reached for {signal.instrument}")
                continue

            # Dedup: skip if same instrument+direction was signaled in the last 5 minutes.
            # Prevents the same bar triggering repeated identical signals across cycles.
            if self._is_duplicate_signal(signal):
                log.debug("Duplicate signal suppressed: %s %s", signal.instrument, signal.direction.value)
                continue
            self._record_signal_time(signal)

            # Spread proxy: skip momentum entries when spread is abnormally compressed
            # (<80% of rolling baseline). Thin/pre-news conditions produce deceptive pullbacks.
            if state.regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
                sr = spread_ratios.get(choice.instrument, 1.0)
                if sr < 0.8:
                    log.debug("Spread compressed — skipping momentum entry: %s (%.2f×)",
                              choice.instrument, sr)
                    self._db.log_signal(signal, executed=False,
                                        rejection_reason=f"spread compressed ({sr:.2f}× baseline)")
                    continue

            decision = self._risk.evaluate(
                signal=signal, balance=balance,
                open_positions=self._portfolio.positions,
                daily_pnl=self._daily_pnl(),
                correlation_matrix=corr_matrix,
                spread_ratio=spread_ratios.get(choice.instrument, 1.0),
            )
            if not decision.approved:
                log.info("Signal rejected for %s: %s", choice.instrument, decision.reason)
                self._db.log_signal(signal, executed=False, rejection_reason=decision.reason)
                continue

            ai_decision = None
            if self._ai is not None:
                ai_decision = await self._ai.validate(signal, state, balance)
                if ai_decision.action == "VETO":
                    log.info("AI vetoed %s: %s", choice.instrument, ai_decision.reasoning)
                    self._db.log_signal(signal, executed=False,
                                        ai_decision="VETO", ai_reasoning=ai_decision.reasoning)
                    continue
                if ai_decision.action == "MODIFY":
                    if ai_decision.stop_loss is not None:
                        signal = signal.model_copy(update={"stop_loss": ai_decision.stop_loss})
                    if ai_decision.take_profit is not None:
                        signal = signal.model_copy(update={"take_profit": ai_decision.take_profit})
                    log.info("AI modified SL/TP for %s: %s",
                             choice.instrument, ai_decision.reasoning)

            result = await self._execution.place_order(signal, decision.lot_size)
            self._db.log_signal(
                signal, executed=(result.status == "FILLED"),
                ai_decision=ai_decision.action if ai_decision else None,
                ai_reasoning=ai_decision.reasoning if ai_decision else None,
            )
            if result.status == "FILLED":
                log.info("Order placed  %s  #%s  SL=%.5f  TP=%.5f",
                         choice.instrument, result.ticket, signal.stop_loss, signal.take_profit)
            else:
                log.warning("Order REJECTED for %s: %s", choice.instrument, result.error)

        # ── London Breakout parallel pass ──────────────────────────────────────
        lb_pairs = set(self._cfg.strategy.london_breakout.pairs)
        lb_states = [s for s in regime_states if s.instrument in lb_pairs]
        for state in lb_states:
            if not self._in_session(state.instrument):
                continue
            lb_df = await self._fetcher.fetch_ohlcv(
                state.instrument, self._cfg.timeframes.entry, bars=200,
            )
            if lb_df is None or lb_df.empty:
                continue
            for strat in self._parallel_strategies:
                signal = strat.generate_signal(lb_df, state)
                if signal is None:
                    continue
                if self._is_duplicate_signal(signal):
                    log.debug("LB duplicate suppressed: %s %s",
                              signal.instrument, signal.direction.value)
                    continue
                self._record_signal_time(signal)
                decision = self._risk.evaluate(
                    signal=signal,
                    balance=balance,
                    open_positions=self._portfolio.positions,
                    daily_pnl=self._daily_pnl(),
                    correlation_matrix=corr_matrix,
                    spread_ratio=spread_ratios.get(state.instrument, 1.0),
                )
                if not decision.approved:
                    log.info("LB signal rejected for %s: %s",
                             state.instrument, decision.reason)
                    self._db.log_signal(signal, executed=False, rejection_reason=decision.reason)
                    continue
                ai_decision = None
                if self._ai is not None:
                    ai_decision = await self._ai.validate(signal, state, balance)
                    if ai_decision.action == "VETO":
                        log.info("AI vetoed LB %s: %s",
                                 state.instrument, ai_decision.reasoning)
                        self._db.log_signal(
                            signal, executed=False,
                            ai_decision="VETO", ai_reasoning=ai_decision.reasoning,
                        )
                        continue
                    if ai_decision.action == "MODIFY":
                        if ai_decision.stop_loss is not None:
                            signal = signal.model_copy(
                                update={"stop_loss": ai_decision.stop_loss}
                            )
                        if ai_decision.take_profit is not None:
                            signal = signal.model_copy(
                                update={"take_profit": ai_decision.take_profit}
                            )
                        log.info("AI modified LB SL/TP for %s: %s",
                                 state.instrument, ai_decision.reasoning)
                result = await self._execution.place_order(signal, decision.lot_size)
                self._db.log_signal(
                    signal,
                    executed=(result.status == "FILLED"),
                    ai_decision=ai_decision.action if ai_decision else None,
                    ai_reasoning=ai_decision.reasoning if ai_decision else None,
                )
                if result.status == "FILLED":
                    log.info(
                        "LB order placed  %s  #%s  SL=%.5f  TP=%.5f",
                        state.instrument, result.ticket,
                        signal.stop_loss, signal.take_profit,
                    )
                else:
                    log.warning("LB order REJECTED for %s: %s",
                                state.instrument, result.error)

        # ── deferred Supabase writes — happen AFTER all orders are placed ─────────
        # Supabase network issues must never delay or block trade execution.
        self._db.update_bot_status(
            "RUNNING",
            balance=balance,
            equity=equity,
            float_pnl=self._portfolio.unrealized_pnl(),
        )
        for state in regime_states:
            self._db.snapshot_regime(state)
        await self._write_evaluations(regime_states)
        await self._write_daily_summary_if_new_day(balance)

    async def _write_evaluations(self, regime_states: list[RegimeState]) -> None:
        for state in regime_states:
            inst = state.instrument
            try:
                in_session = self._in_session(inst)
                allowed = self._session_allowed_regimes(inst)
                mtf = None
                if state.regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
                    direction = "BUY" if state.regime == Regime.TRENDING_UP else "SELL"
                    mtf = (await self._h4_aligned(inst, direction)
                           and await self._d1_aligned(inst, direction))
                # Skip OHLCV fetch for out-of-session instruments — evaluate() will
                # gate them immediately and never use the data.
                edf = None if not in_session else await self._fetcher.fetch_ohlcv(
                    inst, self._cfg.timeframes.entry, bars=200)
                ev = evaluate(
                    inst, state, edf, self._cfg,
                    self._strategies.get(state.regime),
                    in_session=in_session, allowed_regimes=allowed, mtf_aligned=mtf,
                    is_mean_rev_only=inst in _MEAN_REV_ONLY,
                    is_momentum_only=inst in _MOMENTUM_ONLY,
                )
                self._db.upsert_signal_evaluation(ev)
            except Exception:
                log.exception("Evaluation write failed for %s", inst)

    # ── closed trade detection ────────────────────────────────────────────────

    async def reconcile_positions_table(self) -> None:
        """Make the positions table mirror live MT5 state, once at startup.

        _detect_closed_trades() only prunes positions that close while the bot
        is running — it diffs against an in-memory baseline (_open_tickets) that
        starts empty. A position that closes while the bot is down is therefore
        never diffed away and lingers in the positions table. Reconcile against
        live MT5 here, and seed the baseline so the first cycle has a reference.
        """
        await self._portfolio.sync()
        live = {p.ticket: p for p in self._portfolio.positions}
        for ticket in self._db.list_position_tickets() - set(live):
            log.info("Reconcile: removing stale position #%d (closed in MT5)", ticket)
            self._db.delete_position(ticket)
        self._open_tickets = dict(live)

    async def _detect_closed_trades(self) -> None:
        current = {p.ticket: p for p in self._portfolio.positions}
        closed = set(self._open_tickets) - set(current)

        for ticket in closed:
            pos = self._open_tickets[ticket]
            exit_price, profit, closed_at = await self._fetch_close_deal(pos)
            duration = (
                int((closed_at - pos.opened_at).total_seconds() / 60)
                if closed_at else None
            )
            log.info(
                "Trade closed  #%d %s %s  entry=%.5f  exit=%.5f  P&L=%.2f  (%s min)",
                ticket, pos.instrument, pos.direction.value,
                pos.entry_price, exit_price or 0, profit or 0, duration,
            )
            self._db.record_trade(
                ticket=ticket,
                instrument=pos.instrument,
                direction=pos.direction.value,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                volume=pos.volume,
                profit=profit,
                opened_at=pos.opened_at.isoformat(),
                closed_at=closed_at.isoformat() if closed_at else None,
                strategy=pos.strategy,
                regime=pos.regime.value,
                duration_minutes=duration,
            )
            if profit is not None:
                self._accumulate_realized_pnl(profit)

            # A + C: record losses for cooldown and daily loss-count tracking
            if profit is not None and profit < 0:
                now = datetime.now(timezone.utc)
                self._sl_cooldown[pos.instrument] = now  # A: start 60-min cooldown
                today = now.date()
                if today != self._daily_sl_date:           # C: reset at midnight
                    self._daily_sl_counts.clear()
                    self._daily_sl_date = today
                key = (pos.instrument, pos.direction.value)
                self._daily_sl_counts[key] = self._daily_sl_counts.get(key, 0) + 1
                log.info(
                    "Loss recorded %s %s — cooldown started, daily SL count=%d",
                    pos.instrument, pos.direction.value, self._daily_sl_counts[key],
                )

            # Remove from positions table — trades table has the full record
            try:
                self._db._client.table("positions").delete().eq("ticket", ticket).execute()
            except Exception as exc:
                log.warning("Could not delete closed position #%d from DB: %s", ticket, exc)

        self._open_tickets = dict(current)
        # Un-gate any tickets that were closed externally so they don't
        # stay in _close_attempted permanently across daily sessions.
        self._close_attempted -= closed

    async def _fetch_close_deal(
        self, pos: Position
    ) -> tuple[Optional[float], Optional[float], Optional[datetime]]:
        try:
            from datetime import timedelta
            from_date = pos.opened_at.strftime("%Y-%m-%d")
            # Add 1 day so the library's midnight cutoff includes all of today's deals
            to_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
            content = await self._mcp.call_tool("get_deals",
                                                {"from_date": from_date, "to_date": to_date})
            text = content[0].text if isinstance(content, list) else str(content)
            df = pd.read_csv(io.StringIO(text), index_col=0)

            if df.empty:
                return None, pos.profit, datetime.now(timezone.utc)

            pos_col = "position_id" if "position_id" in df.columns else "position"
            out = df[(df[pos_col] == pos.ticket) & (df["entry"] == 1)]
            if out.empty:
                return None, pos.profit, datetime.now(timezone.utc)

            deal = out.iloc[-1]
            exit_price = float(deal["price"]) if deal.get("price") else None
            profit = float(deal["profit"]) if "profit" in deal.index else pos.profit

            closed_at = pd.Timestamp(out.index[-1]).to_pydatetime()
            if closed_at.tzinfo is None:
                closed_at = closed_at.replace(tzinfo=timezone.utc)

            return exit_price, profit, closed_at

        except Exception as exc:
            log.warning("Could not fetch close deal for #%d: %s", pos.ticket, exc)
            return None, pos.profit, datetime.now(timezone.utc)

    # ── daily P&L ─────────────────────────────────────────────────────────────

    def _accumulate_realized_pnl(self, profit: float) -> None:
        if date.today() != self._pnl_date:
            self._realized_pnl_today = 0.0
            self._pnl_date = date.today()
        self._realized_pnl_today += profit

    def _daily_pnl(self) -> float:
        if date.today() != self._pnl_date:
            return self._portfolio.unrealized_pnl()
        return self._realized_pnl_today + self._portfolio.unrealized_pnl()

    # ── daily performance summary ─────────────────────────────────────────────

    async def _write_daily_summary_if_new_day(self, current_balance: float) -> None:
        """On first cycle of a new calendar day, write yesterday's summary."""
        today = date.today()
        if today == self._pnl_date:
            return  # same day, nothing to summarise yet

        yesterday = self._pnl_date
        try:
            result = self._db._client.table("trades") \
                .select("profit") \
                .gte("closed_at", yesterday.isoformat()) \
                .lt("closed_at", today.isoformat()) \
                .execute()
            rows = result.data or []
            pnls = [float(r["profit"]) for r in rows if r.get("profit") is not None]

            if pnls:
                import numpy as np
                wins = sum(1 for p in pnls if p > 0)
                win_rate = wins / len(pnls)
                total_profit = sum(pnls)
                sharpe = (np.mean(pnls) / np.std(pnls) * (252 ** 0.5)
                          if np.std(pnls) > 0 else 0.0)
                # Drawdown = max peak-to-trough in equity curve
                equity = pd.Series(pnls).cumsum() + (current_balance - total_profit)
                running_max = equity.cummax()
                drawdown = float(((running_max - equity) / running_max).max())

                self._db._client.table("performance_daily").upsert({
                    "date": yesterday.isoformat(),
                    "total_trades": len(pnls),
                    "win_rate": round(win_rate, 4),
                    "profit": round(total_profit, 2),
                    "drawdown": round(drawdown, 4),
                    "balance": round(current_balance, 2),
                    "sharpe": round(float(sharpe), 4),
                }, on_conflict="date").execute()

                log.info(
                    "Daily summary %s: %d trades  win=%.0f%%  P&L=%.2f  DD=%.1f%%  Sharpe=%.2f",
                    yesterday, len(pnls), win_rate * 100, total_profit,
                    drawdown * 100, sharpe,
                )
        except Exception as exc:
            log.warning("Failed to write daily summary: %s", exc)

        # Reset for new day
        self._realized_pnl_today = 0.0
        self._pnl_date = today

    # ── position management ───────────────────────────────────────────────────

    async def _manage_positions(self) -> None:
        positions = self._portfolio.positions
        if not positions:
            return

        # Fetch live prices for all open instruments in one pass
        live_prices: dict[str, dict] = {}
        for inst in {p.instrument for p in positions}:
            try:
                live_prices[inst] = await self._mcp.call_tool(
                    "get_symbol_info", {"symbol": inst}
                )
            except Exception:
                pass

        expired_tickets: set[int] = set()

        # Time-based exit — skip tickets we've already attempted this session
        # to avoid hammering MT5 every cycle when the market is closed.
        for pos in self._portfolio.positions_exceeding_holding_time(
            self._cfg.execution.max_holding_hours
        ):
            if pos.ticket in self._close_attempted:
                continue
            log.info("Closing expired #%d %s (held >%dh, P&L=%.2f)",
                     pos.ticket, pos.instrument,
                     self._cfg.execution.max_holding_hours, pos.profit)
            try:
                await self._execution.close_position(pos.ticket)
                self._close_attempted.add(pos.ticket)
            except Exception as exc:
                log.warning("Close failed for #%d %s: %s — will retry next session",
                            pos.ticket, pos.instrument, exc)
                self._close_attempted.add(pos.ticket)
            expired_tickets.add(pos.ticket)

        # Trailing stops + live price upsert
        for pos in positions:
            if pos.ticket in expired_tickets:
                continue

            price_info = live_prices.get(pos.instrument, {})
            bid = float(price_info.get("bid", 0))
            ask = float(price_info.get("ask", bid))

            # Update current_price before persisting to Supabase
            if bid > 0:
                live_price = bid if pos.direction.value == "BUY" else ask
                pos = pos.model_copy(update={"current_price": live_price})

            self._db.upsert_position(pos)

            if not pos.stop_loss or not bid:
                continue

            df = self._cache.get(pos.instrument, self._cfg.timeframes.regime)
            if df is None or len(df) < 20:
                continue
            atr_series = compute_atr(df).dropna()
            if atr_series.empty:
                continue
            atr = float(atr_series.iloc[-1])
            if atr <= 0:
                continue

            new_sl = self._trail_sl(pos, atr, bid, ask)
            if new_sl is not None:
                log.info("Trailing SL  #%d %s: %.5f → %.5f  (ATR=%.5f)",
                         pos.ticket, pos.instrument, pos.stop_loss, new_sl, atr)
                await self._execution.modify_position(pos.ticket, stop_loss=new_sl)

    @staticmethod
    def _trail_sl(pos: Position, atr: float, bid: float, ask: float) -> Optional[float]:
        if not pos.stop_loss:
            return None

        # MR positions go to breakeven sooner (0.5× ATR) to eliminate give-back losses
        # on band reversions that initially move favorably then snap back.
        be_threshold = 0.5 * atr if pos.strategy == "mean_reversion" else 1.0 * atr

        if pos.direction.value == "BUY":
            current = bid
            profit_dist = current - pos.entry_price
            if profit_dist >= 2.0 * atr:
                trail = round(current - atr, 5)
                return trail if trail > pos.stop_loss else None
            elif profit_dist >= be_threshold:
                be = round(pos.entry_price, 5)
                return be if be > pos.stop_loss else None

        elif pos.direction.value == "SELL":
            current = ask
            profit_dist = pos.entry_price - current
            if profit_dist >= 2.0 * atr:
                trail = round(current + atr, 5)
                return trail if trail < pos.stop_loss else None
            elif profit_dist >= be_threshold:
                be = round(pos.entry_price, 5)
                return be if be < pos.stop_loss else None

        return None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _compute_correlation_matrix(self) -> dict[tuple[str, str], float]:
        closes: dict[str, pd.Series] = {}
        for inst in self._cfg.instruments:
            df = self._cache.get(inst, self._cfg.timeframes.regime)
            if df is not None and len(df) >= 30:
                closes[inst] = df["close"].tail(30)
        if len(closes) < 2:
            return {}
        close_df = pd.DataFrame(closes).dropna()
        if len(close_df) < 10:
            return {}
        corr = close_df.corr()
        matrix: dict[tuple[str, str], float] = {}
        cols = list(corr.columns)
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                matrix[(a, b)] = float(corr.loc[a, b])
        return matrix

    def _compute_sharpe_by_instrument(self) -> dict[str, float]:
        try:
            result = self._db._client.table("trades") \
                .select("instrument,profit").execute()
            rows = result.data or []
            if not rows:
                return {i: 1.0 for i in self._cfg.instruments}
            df = pd.DataFrame(rows)
            sharpe: dict[str, float] = {}
            for inst in self._cfg.instruments:
                sub = df[df["instrument"] == inst]["profit"].astype(float)
                if len(sub) >= 5 and sub.std() > 0:
                    sharpe[inst] = float(sub.mean() / sub.std() * (252 ** 0.5))
                else:
                    sharpe[inst] = 1.0
            return sharpe
        except Exception:
            return {i: 1.0 for i in self._cfg.instruments}

    # ── EMA direction helpers ─────────────────────────────────────────────────

    @staticmethod
    def _ema_aligned(df: pd.DataFrame, length: int, direction: str) -> bool:
        """Return True if the last close is on the correct side of an EMA for direction.

        Extracted as a testable pure function; callers supply the already-fetched DataFrame.
        Fails open (True) when the EMA cannot be computed — insufficient data should never
        block a signal.
        """
        ema = ta.ema(df["close"], length=length)
        if ema is None or ema.isna().iloc[-1]:
            return True
        close   = float(df["close"].iloc[-1])
        ema_val = float(ema.iloc[-1])
        return close > ema_val if direction == "BUY" else close < ema_val

    async def _h4_aligned(self, instrument: str, direction: str) -> bool:
        """Return True if the H4 50-EMA direction matches the intended trade direction.

        H1 signals that align with H4 trend win ~60-65%.
        H1 signals counter to H4 trend win only ~30-35%.
        Fails open (returns True) if H4 data is unavailable.
        """
        try:
            df_h4 = await self._fetcher.fetch_ohlcv(instrument, "H4", bars=100)
            return self._ema_aligned(df_h4, length=50, direction=direction)
        except Exception:
            return True   # fail open — never block on error

    async def _d1_aligned(self, instrument: str, direction: str) -> bool:
        """Return True if the D1 50-EMA direction matches the intended trade direction.

        Adding D1 alignment on top of H4 alignment compounds the multi-timeframe filter:
        H1 + H4 + D1 all agreeing yields ~63-70% win rate vs ~55-62% for H1 + H4 alone.
        Fails open (returns True) if D1 data is unavailable.
        """
        try:
            df_d1 = await self._fetcher.fetch_ohlcv(instrument, "D1", bars=100)
            return self._ema_aligned(df_d1, length=50, direction=direction)
        except Exception:
            return True   # fail open — never block on error

    # ── session filter ────────────────────────────────────────────────────────

    # (start_hour_utc_inclusive, end_hour_utc_exclusive)
    # Only trade during high-liquidity windows to avoid thin-market noise.
    _SESSION_HOURS: dict[str, tuple[int, int]] = {
        "EURUSD": (0, 24), # Mean-rev only — Asian session is the prime window; no hour gate
        "EUR": (7,  21),   # London 07–16 + NY 13–21 (other EUR crosses)
        "GBPUSD": (7, 18), # London + NY overlap — afternoon has strong GBP moves
        "GBP": (7,  18),   # GBPJPYm: London + NY overlap
        # USDJPY's quote currency is JPY, but prefix matching keys on the *base*
        # currency, so it never matched the "JPY" rule below and fell through to
        # the always-on default. Give it an explicit window matching JPY intent.
        "USDJPY": (0, 20), # Tokyo 00–09 + London 07–16 + NY 13–20
        "JPY": (0,  20),   # Tokyo 00–09 + London 07–16 + NY 13–20
        "CHF": (7,  21),
        "CAD": (12, 21),   # NY session (CAD pairs move with NY)
        "AUD": (0,  17),   # Sydney 22–07 UTC + London 07–17
        "NZD": (0,  17),
        "XAU": (1,  21),   # Asian 01–07 (mean rev) + London/NY 07–21 (momentum); 00:00 skipped (Sydney gap)
        "XAG": (7,  21),
        "US5": (12, 21),   # Pre-market 12–14 (mean rev) + NYSE 14–21 (momentum)
        "US3": (13, 21),
        "UST": (13, 21),   # USTEC: full NYSE session
        "NAS": (13, 21),
        "GER": (7,  17),   # Frankfurt/Xetra
        "UK1": (7,  16),   # London Stock Exchange
        # Crypto trades 24/7 but US hours (13–22 UTC) have peak volume and cleanest momentum.
        # Asian session (01–08 UTC) trades as momentum only — no MR due to gap/news risk.
        # Sunday 22:00–01:00 UTC blocked: weekly gap and thin weekend liquidity.
        "BTC": (1,  22),   # Bitcoin: Asian + London + NY; blocks Sun 22:00–Mon 01:00
        "ETH": (8,  22),   # Ethereum: London + NY only (less Asian liquidity than BTC)
    }

    # Instruments where strategy type depends on the current UTC session.
    # Each entry: (start_hour_inclusive, end_hour_exclusive, allowed_regimes).
    # Hours outside all listed windows are blocked (frozenset() returned).
    _SESSION_REGIME_GATES: dict[str, list[tuple[int, int, frozenset]]] = {
        "XAU": [
            # Allow both MR (RANGING) and momentum (TRENDING) at all hours —
            # XAU ranges frequently during London/NY and is a reliable MR pair.
            (1, 21, frozenset({Regime.RANGING, Regime.CHOPPY,
                               Regime.TRENDING_UP, Regime.TRENDING_DOWN})),
        ],
        "US5": [
            # Allow MR in all regimes throughout the session — on choppy days
            # US500 mean-reverts at band edges just as reliably as it trends.
            (12, 21, frozenset({Regime.RANGING, Regime.CHOPPY,
                                Regime.TRENDING_UP, Regime.TRENDING_DOWN})),
        ],
        # Crypto: momentum only across all session hours.
        # No mean-reversion window — gap/news risk makes band-touch MR unreliable.
        "BTC": [
            (1,  22, frozenset({Regime.TRENDING_UP, Regime.TRENDING_DOWN})),
        ],
        "ETH": [
            (8,  22, frozenset({Regime.TRENDING_UP, Regime.TRENDING_DOWN})),
        ],
    }

    @staticmethod
    def _in_session(instrument: str) -> bool:
        """Return True if the current UTC hour is within the primary liquidity
        window for this instrument.  Defaults to True for unknown prefixes."""
        hour  = datetime.now(timezone.utc).hour
        clean = instrument.rstrip("m").upper()
        for prefix, (start, end) in TradingBot._SESSION_HOURS.items():
            if clean.startswith(prefix):
                return start <= hour < end
        return True   # unknown instrument — don't gate it

    @staticmethod
    def _session_allowed_regimes(instrument: str) -> Optional[frozenset]:
        """Return the set of Regime values permitted for signal generation right now.

        Returns None if this instrument has no session-based routing rule.
        Returns an empty frozenset if the instrument is in its session window but
        the current hour falls outside all defined strategy sub-windows.
        """
        hour  = datetime.now(timezone.utc).hour
        clean = instrument.rstrip("m").upper()
        for prefix, gates in TradingBot._SESSION_REGIME_GATES.items():
            if clean.startswith(prefix):
                for start, end, allowed in gates:
                    if start <= hour < end:
                        return allowed
                return frozenset()  # in session window but between strategy bands
        return None  # no rule — all regimes permitted

    @staticmethod
    def _mandate_blocks(instrument: str, regime: Regime) -> bool:
        """Return True if this instrument's strategy mandate forbids trading the
        current regime.

        EURUSD-style pairs are mean-reversion only — blocked in trending regimes.
        High-ADR pairs are momentum only — blocked in BOTH ranging AND choppy
        regimes, since the regime→strategy map routes RANGING *and* CHOPPY to mean
        reversion, and these pairs must never emit a mean-reversion signal.
        """
        if instrument in _MEAN_REV_ONLY and regime in (
            Regime.TRENDING_UP, Regime.TRENDING_DOWN
        ):
            return True
        if instrument in _MOMENTUM_ONLY and regime in (
            Regime.RANGING, Regime.CHOPPY
        ):
            return True
        return False

    # ── signal dedup guard ────────────────────────────────────────────────────

    def _is_duplicate_signal(self, signal) -> bool:
        """Return True if the same instrument+direction signal was recorded recently.

        Prevents the same setup from generating back-to-back signals across
        consecutive 60-second cycles when price hasn't moved off the trigger bar.
        """
        key = (signal.instrument, signal.direction.value)
        last = self._last_signal_time.get(key)
        if last is None:
            return False
        return (datetime.now(timezone.utc) - last).total_seconds() < self._signal_dedup_seconds

    def _record_signal_time(self, signal) -> None:
        key = (signal.instrument, signal.direction.value)
        self._last_signal_time[key] = datetime.now(timezone.utc)

    async def _compute_spread_ratios(self) -> dict[str, float]:
        ratios: dict[str, float] = {}
        alpha = 0.05  # EMA factor ≈ 20-period rolling average
        for instrument in self._cfg.instruments:
            try:
                info = await self._mcp.call_tool("get_symbol_info", {"symbol": instrument})
                current = float(info.get("spread", 0))
                prev = self._spread_ema.get(instrument, current)
                ema = alpha * current + (1.0 - alpha) * prev
                self._spread_ema[instrument] = ema
                ratios[instrument] = current / ema if ema > 0 else 1.0
            except Exception:
                ratios[instrument] = 1.0
        return ratios
