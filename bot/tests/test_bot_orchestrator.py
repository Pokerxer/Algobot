import pytest
from unittest.mock import MagicMock
from src.bot import TradingBot
from src.config.schema import AppConfig
from src.mcp_client.fake import FakeMCPClient


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
