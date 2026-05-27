from typing import Any


class FakeMCPClient:
    def __init__(self, responses: dict[str, Any]):
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name not in self._responses:
            raise KeyError(f"FakeMCPClient has no response for tool '{name}'")
        return self._responses[name]

    async def close(self) -> None:
        pass
