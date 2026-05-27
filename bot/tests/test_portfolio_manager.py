import pytest
from datetime import datetime, timedelta, timezone
from src.portfolio.manager import PortfolioManager
from src.mcp_client.fake import FakeMCPClient
from src.models.position import Position
from src.models.signal import Direction
from src.models.regime import Regime


def _mcp_pos(ticket=1, profit=10):
    return {"ticket": ticket, "symbol": "EURUSD", "type": "BUY",
            "open_price": 1.085, "current_price": 1.087, "volume": 0.1,
            "profit": profit, "stop_loss": 1.082, "take_profit": 1.091,
            "time": int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())}


@pytest.mark.asyncio
async def test_sync_loads_positions():
    mcp = FakeMCPClient(responses={"get_positions": [_mcp_pos()]})
    pm = PortfolioManager(mcp)
    await pm.sync()
    assert pm.positions[0].ticket == 1


@pytest.mark.asyncio
async def test_total_unrealized_pnl():
    mcp = FakeMCPClient(responses={"get_positions": [
        _mcp_pos(ticket=1, profit=20), _mcp_pos(ticket=2, profit=-5),
    ]})
    pm = PortfolioManager(mcp)
    await pm.sync()
    assert pm.unrealized_pnl() == 15


def test_positions_exceeding_holding_time():
    pm = PortfolioManager(FakeMCPClient(responses={}))
    old = Position(ticket=1, instrument="EURUSD", direction=Direction.BUY,
                   entry_price=1.085, volume=0.01,
                   opened_at=datetime.now(timezone.utc) - timedelta(hours=25),
                   strategy="momentum", regime=Regime.TRENDING_UP)
    fresh = Position(ticket=2, instrument="EURUSD", direction=Direction.BUY,
                     entry_price=1.085, volume=0.01,
                     opened_at=datetime.now(timezone.utc),
                     strategy="momentum", regime=Regime.TRENDING_UP)
    pm._positions = [old, fresh]
    expired = pm.positions_exceeding_holding_time(max_hours=24)
    assert [p.ticket for p in expired] == [1]
