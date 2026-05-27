import pytest
import pandas as pd
from src.data.fetcher import DataFetcher
from src.data.cache import OHLCVCache
from src.mcp_client.fake import FakeMCPClient


def _fake_rates(n=50):
    return [
        {"time": 1704067200 + i * 3600, "open": 1.0, "high": 1.1,
         "low": 0.9, "close": 1.05, "tick_volume": 100}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_fetcher_returns_dataframe():
    mcp = FakeMCPClient(responses={"get_rates": _fake_rates(50)})
    df = await DataFetcher(mcp, OHLCVCache()).fetch_ohlcv("EURUSD", "H1", bars=50)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 50
    assert {"open", "high", "low", "close", "volume"}.issubset(df.columns)


@pytest.mark.asyncio
async def test_fetcher_uses_cache_when_fresh():
    mcp = FakeMCPClient(responses={"get_rates": _fake_rates(50)})
    fetcher = DataFetcher(mcp, OHLCVCache(ttl_seconds={"H1": 3600}))
    await fetcher.fetch_ohlcv("EURUSD", "H1", bars=50)
    await fetcher.fetch_ohlcv("EURUSD", "H1", bars=50)
    assert len(mcp.calls) == 1


@pytest.mark.asyncio
async def test_fetcher_passes_correct_arguments():
    mcp = FakeMCPClient(responses={"get_rates": _fake_rates(10)})
    await DataFetcher(mcp, OHLCVCache()).fetch_ohlcv("XAUUSD", "M15", bars=10)
    name, args = mcp.calls[0]
    assert name == "get_rates"
    assert args == {"symbol": "XAUUSD", "timeframe": "M15", "count": 10}
