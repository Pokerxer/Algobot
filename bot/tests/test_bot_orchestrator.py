import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from src.bot import TradingBot
from src.config.schema import AppConfig
from src.mcp_client.fake import FakeMCPClient
from src.models.position import Position
from src.models.signal import Direction, Signal
from src.models.regime import Regime


def _config():
    return AppConfig(account={"starting_balance": 500}, instruments=["EURUSD"])


def _rates(n=500):
    return [{"time": 1704067200 + i * 3600, "open": 1.1, "high": 1.11,
             "low": 1.09, "close": 1.10 + 0.0001 * i, "tick_volume": 1000}
            for i in range(n)]


@pytest.mark.asyncio
async def test_runs_one_cycle():
    mcp = FakeMCPClient(responses={
        "get_rates": _rates(), "get_positions": [],
        "account_info": {"balance": 500},
        "get_symbol_info": {"spread": 1.0, "avg_spread": 1.0},
    })
    bot = TradingBot(config=_config(), mcp=mcp, supabase_logger=MagicMock())
    await bot.run_cycle()
    tool_names = [n for n, _ in mcp.calls]
    assert "get_rates" in tool_names
    assert "get_positions" in tool_names


@pytest.mark.asyncio
async def test_logs_regime_snapshot():
    mcp = FakeMCPClient(responses={
        "get_rates": _rates(), "get_positions": [],
        "account_info": {"balance": 500},
        "get_symbol_info": {"spread": 1.0, "avg_spread": 1.0},
    })
    supabase = MagicMock()
    await TradingBot(_config(), mcp, supabase).run_cycle()
    supabase.snapshot_regime.assert_called()


# ── D1 EMA alignment (pure static helper) ────────────────────────────────────

def _ema_df(n: int = 100, close_above_ema: bool = True):
    """DataFrame where 50-EMA is calculable and last close is above/below it."""
    close = np.linspace(1.0, 1.01, n)   # gentle upward slope so EMA ~= 1.005
    if not close_above_ema:
        close[-1] = 0.90   # force close well below the EMA
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def test_ema_aligned_buy_true_when_price_above_ema():
    assert TradingBot._ema_aligned(_ema_df(close_above_ema=True), 50, "BUY") is True


def test_ema_aligned_buy_false_when_price_below_ema():
    assert TradingBot._ema_aligned(_ema_df(close_above_ema=False), 50, "BUY") is False


def test_ema_aligned_sell_true_when_price_below_ema():
    assert TradingBot._ema_aligned(_ema_df(close_above_ema=False), 50, "SELL") is True


def test_ema_aligned_sell_false_when_price_above_ema():
    assert TradingBot._ema_aligned(_ema_df(close_above_ema=True), 50, "SELL") is False


# ── MR breakeven at 0.5 × ATR ────────────────────────────────────────────────

def _make_pos(strategy: str, entry: float = 1.1000, sl: float = 1.0800,
              direction=Direction.BUY):
    return Position(
        ticket=1, instrument="EURUSDm", direction=direction,
        entry_price=entry, volume=0.05,
        opened_at=datetime.now(timezone.utc),
        stop_loss=sl, strategy=strategy, regime=Regime.RANGING,
    )


def test_mr_position_moves_to_breakeven_at_half_atr():
    """MR positions trigger breakeven when profit ≥ 0.5 × ATR."""
    atr = 0.0100
    entry = 1.1000
    pos = _make_pos("mean_reversion", entry=entry, sl=entry - 2 * atr)
    bid = entry + 0.0060  # 0.6 × ATR profit — clearly above the 0.5× threshold
    result = TradingBot._trail_sl(pos, atr=atr, bid=bid, ask=bid)
    assert result == round(entry, 5)


def test_momentum_position_does_not_trigger_breakeven_at_half_atr():
    """Momentum positions should NOT move to breakeven at 0.6 × ATR — needs 1 × ATR."""
    atr = 0.0100
    entry = 1.1000
    pos = _make_pos("momentum", entry=entry, sl=entry - 2 * atr)
    bid = entry + 0.0060  # 0.6 × ATR — above MR threshold but below 1× ATR (momentum needs)
    result = TradingBot._trail_sl(pos, atr=atr, bid=bid, ask=bid)
    assert result is None


def test_momentum_position_moves_to_breakeven_at_one_atr():
    """Momentum positions trigger breakeven at 1 × ATR."""
    atr = 0.0100
    entry = 1.1000
    pos = _make_pos("momentum", entry=entry, sl=entry - 2 * atr)
    bid = entry + 0.0100  # exactly 1 × ATR profit
    result = TradingBot._trail_sl(pos, atr=atr, bid=bid, ask=bid)
    assert result == round(entry, 5)


# ── Signal dedup guard ────────────────────────────────────────────────────────

def _sig(instrument="EURUSDm", direction=Direction.BUY):
    return Signal(
        instrument=instrument, direction=direction,
        entry_price=1.085, stop_loss=1.082, take_profit=1.091,
        confidence=0.7, regime=Regime.RANGING, strategy="mean_reversion",
    )


def test_dedup_allows_first_signal():
    """First signal for an instrument is never blocked."""
    bot = TradingBot(config=_config(), mcp=MagicMock(), supabase_logger=MagicMock())
    assert bot._is_duplicate_signal(_sig()) is False


def test_dedup_blocks_same_signal_within_5_minutes():
    """Same instrument + direction within 5 minutes is a duplicate."""
    bot = TradingBot(config=_config(), mcp=MagicMock(), supabase_logger=MagicMock())
    sig = _sig()
    bot._record_signal_time(sig)
    assert bot._is_duplicate_signal(sig) is True


def test_dedup_allows_same_signal_after_5_minutes():
    """Same instrument + direction after 5 minutes is allowed again."""
    bot = TradingBot(config=_config(), mcp=MagicMock(), supabase_logger=MagicMock())
    sig = _sig()
    # Simulate a signal recorded 6 minutes ago
    key = (sig.instrument, sig.direction.value)
    bot._last_signal_time[key] = datetime.now(timezone.utc) - timedelta(minutes=6)
    assert bot._is_duplicate_signal(sig) is False


def test_dedup_allows_opposite_direction():
    """BUY and SELL on the same instrument are independent."""
    bot = TradingBot(config=_config(), mcp=MagicMock(), supabase_logger=MagicMock())
    buy_sig = _sig(direction=Direction.BUY)
    sell_sig = _sig(direction=Direction.SELL)
    bot._record_signal_time(buy_sig)
    assert bot._is_duplicate_signal(sell_sig) is False


def test_dedup_allows_different_instrument():
    """Signals on different instruments are independent."""
    bot = TradingBot(config=_config(), mcp=MagicMock(), supabase_logger=MagicMock())
    eur_sig = _sig(instrument="EURUSDm")
    gbp_sig = _sig(instrument="GBPUSDm")
    bot._record_signal_time(eur_sig)
    assert bot._is_duplicate_signal(gbp_sig) is False


def test_parallel_strategies_contains_london_breakout():
    from src.strategies.london_breakout import LondonBreakoutStrategy
    bot = TradingBot(config=_config(), mcp=MagicMock(), supabase_logger=MagicMock())
    assert hasattr(bot, "_parallel_strategies")
    assert any(isinstance(s, LondonBreakoutStrategy) for s in bot._parallel_strategies)
