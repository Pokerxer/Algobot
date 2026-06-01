import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import main as main_module


@pytest.mark.asyncio
async def test_hard_stop_after_10_consecutive_non_mcp_failures():
    """main() must exit after 10 consecutive non-MCP failures, not loop forever.

    With the bug (consecutive_failures >= 3 triggers reconnect), the bot
    reconnects every 3 failures and never reaches the >= 10 hard-stop.
    After the fix (only MCP failures trigger reconnect), non-MCP failures
    count up to 10 and break the loop cleanly.
    """
    call_count = 0

    async def always_fail():
        nonlocal call_count
        call_count += 1
        if call_count > 15:
            # Safety valve: prevents infinite loops in the pre-fix state.
            # With the bug, reconnect fires at count=3, resets to 0, repeats.
            # This caps at 15 so the test fails fast rather than hanging.
            raise KeyboardInterrupt("safety: reconnect loop detected — hard-stop never fired")
        raise RuntimeError("non-mcp error — not a connection problem")

    mock_mcp = AsyncMock()
    mock_db = MagicMock()
    mock_config = MagicMock()
    mock_config.ai.enabled = False
    mock_bot = MagicMock()
    mock_bot.run_cycle = always_fail

    async def instant_timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    try:
        with (
            patch.object(main_module, "load_config", return_value=mock_config),
            patch.object(main_module, "_SupabaseRest", return_value=MagicMock()),
            patch.object(main_module, "SupabaseLogger", return_value=mock_db),
            patch.object(main_module, "StdioMCPClient", return_value=mock_mcp),
            patch.object(main_module, "TradingBot", return_value=mock_bot),
            patch.object(main_module.asyncio, "wait_for", side_effect=instant_timeout),
        ):
            await main_module.main()
    except KeyboardInterrupt:
        pass  # bug path: safety valve fired; assertion below will catch it

    assert call_count == 10, (
        f"Expected hard-stop at exactly 10 failures, got {call_count}. "
        "If >10, the consecutive_failures >= 3 reconnect clause is still present."
    )


def test_looks_like_mcp_failure_matches_connection_errors():
    """MCP-related exceptions must be classified as MCP failures → trigger reconnect."""
    assert main_module._looks_like_mcp_failure(ConnectionError("EOF"))
    assert main_module._looks_like_mcp_failure(Exception("JSONDecodeError in response"))
    assert main_module._looks_like_mcp_failure(Exception("McpError: timeout"))
    assert main_module._looks_like_mcp_failure(Exception("BrokenPipe"))
    assert main_module._looks_like_mcp_failure(Exception("Connection closed unexpectedly"))


def test_looks_like_mcp_failure_does_not_match_non_mcp_errors():
    """Non-MCP errors must NOT be classified as MCP failures — they count toward hard-stop."""
    assert not main_module._looks_like_mcp_failure(RuntimeError("database query failed"))
    assert not main_module._looks_like_mcp_failure(ValueError("invalid signal data"))
    assert not main_module._looks_like_mcp_failure(KeyError("missing key in response"))


def test_supabaserest_delete_issues_filtered_delete_request():
    """_SupabaseRest must support delete().

    bot._detect_closed_trades() prunes a closed position with
    table('positions').delete().eq('ticket', t).execute(). Without a delete()
    method the call raises AttributeError (swallowed as a warning), so closed
    positions are recorded as trades but never removed from the positions table.
    """
    rest = main_module._SupabaseRest("https://proj.supabase.co", "svc-key")
    captured = {}

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        captured.update(method=method, url=url, params=params or {}, json=json)
        resp = MagicMock()
        resp.status_code = 204
        resp.content = b""
        return resp

    rest._session.request = fake_request
    rest.table("positions").delete().eq("ticket", 123).execute()

    assert captured["method"] == "DELETE"
    assert captured["url"].endswith("/rest/v1/positions")
    assert captured["params"].get("ticket") == "eq.123"
    assert captured["json"] is None  # a DELETE carries no request body
