from dataclasses import dataclass
from typing import Optional
from src.mcp_client.protocol import MCPClient
from src.models.signal import Signal


@dataclass
class OrderResult:
    ticket: Optional[int]
    filled_price: Optional[float]
    status: str
    error: Optional[str] = None


class ExecutionEngine:
    def __init__(self, mcp: MCPClient):
        self._mcp = mcp

    async def place_order(self, signal: Signal, lot_size: float) -> OrderResult:
        response = await self._mcp.call_tool("place_order", {
            "symbol": signal.instrument,
            "side": signal.direction.value,
            "volume": lot_size,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "type": "MARKET",
        })
        return OrderResult(
            ticket=response.get("ticket"),
            filled_price=response.get("filled_price"),
            status=response.get("status", "PENDING"),
            error=response.get("error"),
        )

    async def close_position(self, ticket: int) -> dict:
        return await self._mcp.call_tool("close_position", {"ticket": ticket})

    async def modify_position(self, ticket: int, stop_loss: Optional[float] = None,
                              take_profit: Optional[float] = None) -> dict:
        args: dict = {"ticket": ticket}
        if stop_loss is not None:
            args["stop_loss"] = stop_loss
        if take_profit is not None:
            args["take_profit"] = take_profit
        return await self._mcp.call_tool("modify_position", args)
