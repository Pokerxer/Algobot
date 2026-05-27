import os
import shlex
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class StdioMCPClient:
    def __init__(self, command: str | None = None):
        cmd_str = command or os.environ.get("MCP_SERVER_COMMAND", "metatrader-mcp-server")
        parts = shlex.split(cmd_str)
        self._params = StdioServerParameters(command=parts[0], args=parts[1:])
        self._session: ClientSession | None = None
        self._stdio_ctx = None
        self._session_ctx = None

    async def connect(self) -> None:
        self._stdio_ctx = stdio_client(self._params)
        read, write = await self._stdio_ctx.__aenter__()
        self._session_ctx = ClientSession(read, write)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("MCP client not connected. Call connect() first.")
        result = await self._session.call_tool(name, arguments)
        return result.content

    async def close(self) -> None:
        if self._session_ctx is not None:
            await self._session_ctx.__aexit__(None, None, None)
        if self._stdio_ctx is not None:
            await self._stdio_ctx.__aexit__(None, None, None)
