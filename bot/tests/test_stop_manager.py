import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from src.bot import TradingBot
from src.config.schema import AppConfig
from src.mcp_client.fake import FakeMCPClient
from src.models.position import Position
from src.models.signal import Direction
from src.models.regime import Regime


def _config():
    return AppConfig(account={"starting_balance": 500}, instruments=["EURUSD"])


def _pos(ticket=1, entry=1.1000, current=1.1000, stop_loss=1.0970, direction=Direction.BUY):
    return Position(
        ticket=ticket, instrument="EURUSD", direction=direction,
        entry_price=entry, current_price=current, volume=0.01,
        profit=round((current - entry) * 10000, 2),
        stop_loss=stop_loss, take_profit=1.1090,
        opened_at=datetime.now(timezone.utc),
        strategy="momentum", regime=Regime.TRENDING_UP,
    )


def _bot_with_positions(positions):
    mcp = FakeMCPClient(responses={"modify_position": {"status": "OK"}})
    bot = TradingBot(_config(), mcp, MagicMock())
    bot._portfolio._positions = positions
    return bot, mcp


@pytest.mark.asyncio
async def test_break_even_at_1r():
    entry, initial_sl = 1.1000, 1.0970  # risk = 0.003
    current = 1.1030                     # move = 0.003 = exactly 1R
    pos = _pos(ticket=42, entry=entry, current=current, stop_loss=initial_sl)
    bot, mcp = _bot_with_positions([pos])
    bot._initial_sl = {42: initial_sl}

    await bot._manage_stops()

    calls = [(n, a) for n, a in mcp.calls if n == "modify_position"]
    assert len(calls) == 1
    assert calls[0][1]["stop_loss"] == entry


@pytest.mark.asyncio
async def test_trail_at_2r():
    entry, initial_sl = 1.1000, 1.0970  # risk = 0.003
    current = 1.1060                     # move = 0.006 = 2R
    pos = _pos(ticket=43, entry=entry, current=current, stop_loss=1.1000)
    bot, mcp = _bot_with_positions([pos])
    bot._initial_sl = {43: initial_sl}

    await bot._manage_stops()

    calls = [(n, a) for n, a in mcp.calls if n == "modify_position"]
    assert len(calls) == 1
    assert calls[0][1]["stop_loss"] == round(current - 0.003, 5)


@pytest.mark.asyncio
async def test_no_update_sl_already_at_break_even():
    entry, initial_sl = 1.1000, 1.0970
    current = 1.1030  # 1R profit, but SL already at entry — no change needed
    pos = _pos(ticket=44, entry=entry, current=current, stop_loss=entry)
    bot, mcp = _bot_with_positions([pos])
    bot._initial_sl = {44: initial_sl}

    await bot._manage_stops()

    calls = [(n, a) for n, a in mcp.calls if n == "modify_position"]
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_no_update_below_1r():
    entry, initial_sl = 1.1000, 1.0970
    current = 1.1010  # move = 0.001 < 1R — nothing to do yet
    pos = _pos(ticket=45, entry=entry, current=current, stop_loss=initial_sl)
    bot, mcp = _bot_with_positions([pos])
    bot._initial_sl = {45: initial_sl}

    await bot._manage_stops()

    calls = [(n, a) for n, a in mcp.calls if n == "modify_position"]
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_break_even_sell_at_1r():
    entry, initial_sl = 1.1000, 1.1030  # SELL, risk = 0.003
    current = 1.0970                     # move down = 0.003 = 1R
    pos = _pos(ticket=46, entry=entry, current=current, stop_loss=initial_sl,
               direction=Direction.SELL)
    bot, mcp = _bot_with_positions([pos])
    bot._initial_sl = {46: initial_sl}

    await bot._manage_stops()

    calls = [(n, a) for n, a in mcp.calls if n == "modify_position"]
    assert len(calls) == 1
    assert calls[0][1]["stop_loss"] == entry


@pytest.mark.asyncio
async def test_cleans_up_closed_tickets():
    bot, _ = _bot_with_positions([])
    bot._initial_sl = {99: 1.0970, 100: 1.0960}

    await bot._manage_stops()

    assert bot._initial_sl == {}
