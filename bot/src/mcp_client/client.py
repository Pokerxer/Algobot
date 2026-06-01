import io
import json
import logging
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

import pandas as pd
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _resolve_exe(name: str) -> str:
    """Find an executable in the current venv's Scripts dir or on PATH."""
    scripts = Path(sys.executable).parent
    for candidate in (scripts / f"{name}.exe", scripts / name):
        if candidate.exists():
            return str(candidate)
    return name  # fallback: rely on PATH


def _text(content) -> str:
    if isinstance(content, list) and content:
        return content[0].text if hasattr(content[0], "text") else str(content[0])
    return str(content)


def _parse_json(content) -> Any:
    return json.loads(_text(content))


def _parse_csv(content) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(_text(content)), index_col=0)


class StdioMCPClient:
    """
    MCP client that adapts the bot's internal tool API to the
    metatrader-mcp-server's actual tool names and response formats.

    Internal → MCP server mapping
      get_rates        → get_candles_latest   (CSV response → list of dicts)
      account_info     → get_account_info     (JSON response)
      get_positions    → get_all_positions    (CSV response → list of dicts)
      place_order      → place_market_order + modify_position
      close_position   → close_position       (ticket → id)
      modify_position  → modify_position      (ticket → id)
      get_symbol_info  → get_symbol_price     (bid/ask → spread/avg_spread)
    """

    def __init__(self, command: str | None = None):
        if command:
            parts = shlex.split(command)
            self._params = StdioServerParameters(command=parts[0], args=parts[1:])
        else:
            exe = _resolve_exe(os.environ.get("MCP_SERVER_COMMAND", "metatrader-mcp-server"))
            args = [
                "--login",     os.environ["MT5_LOGIN"],
                "--password",  os.environ["MT5_PASSWORD"],
                "--server",    os.environ["MT5_SERVER"],
                "--transport", "stdio",
            ]
            if mt5_path := os.environ.get("MT5_PATH"):
                args += ["--path", mt5_path]
            self._params = StdioServerParameters(command=exe, args=args)
        self._session: ClientSession | None = None
        self._stdio_ctx = None
        self._session_ctx = None

    async def connect(self) -> None:
        self._stdio_ctx = stdio_client(self._params, errlog=open(os.devnull, "w"))
        read, write = await self._stdio_ctx.__aenter__()
        self._session_ctx = ClientSession(read, write)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("MCP client not connected. Call connect() first.")
        if name == "get_rates":
            return await self._get_rates(arguments)
        if name == "account_info":
            return await self._account_info()
        if name == "get_positions":
            return await self._get_positions()
        if name == "place_order":
            return await self._place_order(arguments)
        if name == "close_position":
            return await self._raw("close_position", {"id": arguments["ticket"]})
        if name == "modify_position":
            return await self._modify_position(arguments)
        if name == "get_symbol_info":
            return await self._get_symbol_info(arguments)
        result = await self._session.call_tool(name, arguments)
        return result.content

    async def close(self) -> None:
        if self._session_ctx is not None:
            await self._session_ctx.__aexit__(None, None, None)
        if self._stdio_ctx is not None:
            await self._stdio_ctx.__aexit__(None, None, None)

    # ── internal adapters ────────────────────────────────────────────────────

    async def _raw(self, name: str, arguments: dict) -> Any:
        result = await self._session.call_tool(name, arguments)
        return result.content

    async def _get_rates(self, args: dict) -> list[dict]:
        content = await self._raw("get_candles_latest", {
            "symbol_name": args["symbol"],
            "timeframe": args["timeframe"],
            "count": args["count"],
        })
        df = _parse_csv(content)
        rows = []
        for _, row in df.iterrows():
            t = pd.Timestamp(row["time"])
            if t.tzinfo is None:
                t = t.tz_localize("UTC")
            rows.append({
                "time": int(t.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "tick_volume": int(row["tick_volume"]),
            })
        # CSV rows are newest-first; reverse to oldest-first for time series
        return rows[::-1]

    async def _account_info(self) -> dict:
        content = await self._raw("get_account_info", {})
        return _parse_json(content)

    async def _get_positions(self) -> list[dict]:
        content = await self._raw("get_all_positions", {})
        df = _parse_csv(content)
        if df.empty:
            return []
        rows = []
        for _, row in df.iterrows():
            t = pd.Timestamp(row["time"])
            if t.tzinfo is None:
                t = t.tz_localize("UTC")
            sl = row.get("stop_loss")
            tp = row.get("take_profit")
            rows.append({
                "ticket": int(row["id"]),
                "symbol": str(row["symbol"]),
                "type": str(row["type"]),
                "open_price": float(row["open"]),
                "current_price": float(row["open"]),
                "volume": float(row["volume"]),
                "profit": float(row.get("profit", 0)),
                "stop_loss": float(sl) if pd.notna(sl) else None,
                "take_profit": float(tp) if pd.notna(tp) else None,
                "time": int(t.timestamp()),
            })
        return rows

    async def _place_order(self, args: dict) -> dict:
        content = await self._raw("place_market_order", {
            "symbol": args["symbol"],
            "volume": args["volume"],
            "type": args["side"],
        })
        raw_text = _text(content)
        log.info("place_market_order raw response: %s", raw_text[:300])

        # Response: {"error": false, "message": "BUY X 0.02 LOT at 1.33 success (Position ID: 12345)", "data": ...}
        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError:
            log.warning("place_market_order: non-JSON response: %s", raw_text[:200])
            return {"ticket": None, "filled_price": None, "status": "REJECTED", "error": raw_text}

        if result.get("error"):
            log.warning("place_market_order error: %s", result.get("message"))
            return {"ticket": None, "filled_price": None, "status": "REJECTED",
                    "error": result.get("message")}

        # Extract ticket: try nested data dict first, then parse "Position ID: N" from message
        ticket = None
        filled = None
        data = result.get("data")
        if isinstance(data, dict):
            ticket = data.get("order") or data.get("ticket") or data.get("id")
            filled = data.get("price") or data.get("filled_price")
        if not ticket:
            m = re.search(r"Position ID:\s*(\d+)", result.get("message", ""))
            if m:
                ticket = int(m.group(1))
        if not filled:
            m = re.search(r"at\s+([\d.]+)", result.get("message", ""))
            if m:
                filled = float(m.group(1))

        status = "FILLED" if ticket else "REJECTED"
        log.info("place_market_order: ticket=%s filled=%.5f status=%s", ticket, filled or 0, status)

        # Set SL/TP on the position via modify_position.
        # Retry up to 3 times with back-off: MT5 occasionally hasn't registered
        # the new position by the time we call modify immediately after fill.
        if ticket and (args.get("stop_loss") or args.get("take_profit")):
            import asyncio
            modify_args: dict = {"id": ticket}
            if args.get("stop_loss"):
                modify_args["stop_loss"] = args["stop_loss"]
            if args.get("take_profit"):
                modify_args["take_profit"] = args["take_profit"]

            sltp_set = False
            for attempt in range(3):
                if attempt > 0:
                    await asyncio.sleep(1.5 * attempt)
                try:
                    mod_content = await self._raw("modify_position", modify_args)
                    mod_text = _text(mod_content)
                    mod_result = json.loads(mod_text) if mod_text.startswith("{") else {}
                    if not mod_result.get("error", False):
                        log.info("modify_position SL=%.5f TP=%.5f ✓ (attempt %d)",
                                 args.get("stop_loss", 0), args.get("take_profit", 0), attempt + 1)
                        sltp_set = True
                        break
                    log.warning("modify_position attempt %d failed: %s",
                                attempt + 1, mod_result.get("message", mod_text[:100]))
                except Exception as exc:
                    log.warning("modify_position attempt %d exception: %s", attempt + 1, exc)
            if not sltp_set:
                log.error("modify_position FAILED after 3 attempts for ticket=%s — position has NO SL/TP", ticket)

        return {
            "ticket": ticket,
            "filled_price": filled,
            "status": status,
            "error": None,
        }

    async def _modify_position(self, args: dict) -> dict:
        modify_args: dict = {"id": args["ticket"]}
        if args.get("stop_loss") is not None:
            modify_args["stop_loss"] = args["stop_loss"]
        if args.get("take_profit") is not None:
            modify_args["take_profit"] = args["take_profit"]
        content = await self._raw("modify_position", modify_args)
        return _parse_json(content)

    async def _get_symbol_info(self, args: dict) -> dict:
        content = await self._raw("get_symbol_price", {"symbol_name": args["symbol"]})
        price = _parse_json(content)
        bid = float(price.get("bid", 0))
        ask = float(price.get("ask", bid))
        spread = ask - bid
        return {"bid": bid, "ask": ask, "spread": spread, "avg_spread": spread}
