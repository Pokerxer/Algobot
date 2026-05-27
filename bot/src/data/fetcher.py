from typing import Any
import pandas as pd
from src.data.cache import OHLCVCache
from src.mcp_client.protocol import MCPClient


class DataFetcher:
    def __init__(self, mcp: MCPClient, cache: OHLCVCache):
        self._mcp = mcp
        self._cache = cache

    async def fetch_ohlcv(self, instrument: str, timeframe: str,
                          bars: int = 500) -> pd.DataFrame:
        if not self._cache.is_stale(instrument, timeframe):
            cached = self._cache.get(instrument, timeframe)
            if cached is not None and len(cached) >= bars:
                return cached.tail(bars)

        raw = await self._mcp.call_tool(
            "get_rates",
            {"symbol": instrument, "timeframe": timeframe, "count": bars},
        )
        df = self._to_dataframe(raw)
        self._cache.set(instrument, timeframe, df)
        return df

    @staticmethod
    def _to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        if "tick_volume" in df.columns and "volume" not in df.columns:
            df = df.rename(columns={"tick_volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]]
