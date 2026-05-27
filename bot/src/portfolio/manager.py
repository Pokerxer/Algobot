from datetime import datetime, timedelta, timezone
from src.mcp_client.protocol import MCPClient
from src.models.position import Position
from src.models.signal import Direction
from src.models.regime import Regime


class PortfolioManager:
    def __init__(self, mcp: MCPClient):
        self._mcp = mcp
        self._positions: list[Position] = []

    @property
    def positions(self) -> list[Position]:
        return list(self._positions)

    async def sync(self) -> None:
        raw = await self._mcp.call_tool("get_positions", {})
        self._positions = [self._from_mcp(r) for r in raw]

    def unrealized_pnl(self) -> float:
        return sum(p.profit for p in self._positions)

    def positions_exceeding_holding_time(self, max_hours: int) -> list[Position]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
        return [p for p in self._positions if p.opened_at < cutoff]

    @staticmethod
    def _from_mcp(row: dict) -> Position:
        return Position(
            ticket=row["ticket"], instrument=row["symbol"],
            direction=Direction(row["type"]),
            entry_price=row["open_price"],
            current_price=row.get("current_price"),
            volume=row["volume"], profit=row.get("profit", 0),
            stop_loss=row.get("stop_loss"), take_profit=row.get("take_profit"),
            opened_at=datetime.fromtimestamp(row["time"], tz=timezone.utc),
            strategy=row.get("strategy", "unknown"),
            regime=Regime(row.get("regime", "TRENDING_UP")),
        )
