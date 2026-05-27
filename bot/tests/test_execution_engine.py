import pytest
from src.execution.engine import ExecutionEngine, OrderResult
from src.mcp_client.fake import FakeMCPClient
from src.models.signal import Signal, Direction
from src.models.regime import Regime


def _sig():
    return Signal(instrument="EURUSD", direction=Direction.BUY,
                  entry_price=1.085, stop_loss=1.082, take_profit=1.091,
                  confidence=0.8, regime=Regime.TRENDING_UP, strategy="momentum")


@pytest.mark.asyncio
async def test_places_market_order():
    mcp = FakeMCPClient(responses={"place_order": {"ticket": 42,
                                                    "filled_price": 1.0851,
                                                    "status": "FILLED"}})
    result = await ExecutionEngine(mcp).place_order(_sig(), lot_size=0.05)
    assert isinstance(result, OrderResult)
    assert result.ticket == 42
    name, args = mcp.calls[0]
    assert name == "place_order"
    assert args["symbol"] == "EURUSD"
    assert args["volume"] == 0.05


@pytest.mark.asyncio
async def test_close_position():
    mcp = FakeMCPClient(responses={"close_position": {"closed": True}})
    await ExecutionEngine(mcp).close_position(ticket=42)
    assert mcp.calls[0] == ("close_position", {"ticket": 42})


@pytest.mark.asyncio
async def test_returns_rejected_on_failure_payload():
    mcp = FakeMCPClient(responses={"place_order": {"status": "REJECTED",
                                                    "error": "insufficient margin"}})
    result = await ExecutionEngine(mcp).place_order(_sig(), lot_size=0.05)
    assert result.status == "REJECTED"
    assert "margin" in (result.error or "")
