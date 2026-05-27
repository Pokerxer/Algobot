import pytest
from src.mcp_client.fake import FakeMCPClient


@pytest.mark.asyncio
async def test_fake_returns_canned_response():
    client = FakeMCPClient(responses={"account_info": {"balance": 500.0}})
    assert await client.call_tool("account_info", {}) == {"balance": 500.0}


@pytest.mark.asyncio
async def test_fake_raises_on_unknown_tool():
    with pytest.raises(KeyError):
        await FakeMCPClient(responses={}).call_tool("nope", {})


@pytest.mark.asyncio
async def test_fake_records_calls():
    client = FakeMCPClient(responses={"get_rates": []})
    await client.call_tool("get_rates", {"symbol": "EURUSD"})
    assert client.calls == [("get_rates", {"symbol": "EURUSD"})]
