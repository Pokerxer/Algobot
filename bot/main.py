import asyncio
import logging
import os
import signal
from pathlib import Path

# breadcrumb: write directly to a file so we can trace the hang regardless of
# shell I/O redirection
def _crumb(msg: str) -> None:
    with open(Path(__file__).parent / "crumb.log", "a") as f:
        import datetime
        f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")

_crumb("MODULE_START")

from dotenv import load_dotenv
import requests as _requests

_crumb("BASIC_IMPORTS_DONE")

load_dotenv(Path(__file__).parent / ".env")
_crumb("DOTENV_DONE")

# WMI on this host hangs indefinitely (stuck Winmgmt provider), and Python 3.12's
# platform.uname() queries WMI for the Windows version. pandas imports
# platform.machine() at module load (pandas/compat/_constants.py), so any
# `import pandas` deadlocks. Force platform to skip WMI and use its existing
# registry/getwindowsversion() fallback by making the query raise immediately.
import platform as _platform


def _wmi_query_disabled(*_args, **_kwargs):
    raise OSError("WMI disabled: query hangs on this host")


_platform._wmi_query = _wmi_query_disabled
_crumb("WMI_SHIM_INSTALLED")

from src.ai.validator import AIValidator
_crumb("AI_VALIDATOR_IMPORTED")
from src.bot import TradingBot
_crumb("TRADINGBOT_IMPORTED")
from src.config.loader import load_config
from src.db.supabase_client import SupabaseLogger
from src.mcp_client.client import StdioMCPClient
_crumb("ALL_IMPORTS_DONE")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
for _noisy in ("httpx", "httpcore", "mcp", "metatrader_mcp", "metatrader_client",
               "uvicorn", "fastapi", "anyio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("algobot")

_MCP_RECONNECT_ERRORS = (
    "JSONDecodeError", "McpError", "ConnectionError",
    "Connection closed", "EOF", "BrokenPipe",
    "ClosedResourceError", "ClosedResource",
)


class _SupabaseRest:
    """Supabase REST-only client via requests — bypasses Realtime WebSocket init.

    supabase-py 2.x create_client() hangs indefinitely on Windows when the
    Realtime WebSocket handshake stalls. SupabaseLogger only needs .table()
    for REST insert/upsert/select, so this thin adapter is sufficient.
    """

    class _Builder:
        def __init__(self, session: _requests.Session, url: str) -> None:
            self._s, self._url = session, url
            self._method, self._params, self._body, self._hdrs = "GET", {}, None, {}

        def select(self, cols: str = "*"):
            self._params["select"] = cols; return self

        def limit(self, n: int):
            self._params["limit"] = str(n); return self

        def insert(self, data: dict):
            self._method = "POST"; self._body = data
            self._hdrs["Prefer"] = "return=minimal"; return self

        def upsert(self, data: dict, on_conflict: str = "id"):
            self._method = "POST"; self._body = data
            self._params["on_conflict"] = on_conflict
            self._hdrs["Prefer"] = "resolution=merge-duplicates,return=minimal"; return self

        def update(self, data: dict):
            self._method = "PATCH"; self._body = data; return self

        def delete(self):
            self._method = "DELETE"
            self._hdrs["Prefer"] = "return=minimal"; return self

        def _filter(self, col: str, op: str, val):
            new = f"{op}.{val}"
            existing = self._params.get(col)
            if existing is None:
                self._params[col] = new
            elif isinstance(existing, list):
                existing.append(new)
            else:
                self._params[col] = [existing, new]
            return self

        def eq(self, col: str, val):
            return self._filter(col, "eq", val)

        def gte(self, col: str, val):
            return self._filter(col, "gte", val)

        def lt(self, col: str, val):
            return self._filter(col, "lt", val)

        def execute(self):
            r = self._s.request(self._method, self._url,
                                params=self._params, json=self._body,
                                headers=self._hdrs, timeout=10)
            if r.status_code >= 400:
                # Surface PostgREST's response body: raise_for_status() reports
                # only the status line, hiding the real cause (e.g. a missing
                # column → PGRST204). Callers like update_bot_status inspect the
                # error text to decide on a fallback, so the body must be in it.
                raise _requests.HTTPError(
                    f"{r.status_code} {r.reason}: {r.text[:300]}", response=r)
            d = r.json() if r.content else []
            return type("R", (), {"data": d if isinstance(d, list) else [d]})()

    def __init__(self, url: str, key: str) -> None:
        self._session = _requests.Session()
        self._session.headers.update({"apikey": key, "Authorization": f"Bearer {key}",
                                      "Content-Type": "application/json"})
        self._base = f"{url}/rest/v1"

    def table(self, name: str) -> "_SupabaseRest._Builder":
        return self._Builder(self._session, f"{self._base}/{name}")


def _looks_like_mcp_failure(exc: Exception) -> bool:
    msg = f"{type(exc).__name__} {exc}"
    return any(tag in msg for tag in _MCP_RECONNECT_ERRORS)


async def main():
    config = load_config(Path("config/settings.yaml"))
    supabase = _SupabaseRest(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )
    db_logger = SupabaseLogger(supabase)
    _crumb("SUPABASE_REST_DONE")
    log.info("Supabase OK — connecting to MCP server (MT5_PATH=%s)…",
             os.environ.get("MT5_PATH", "auto-detect"))

    _crumb("MCP_CONNECT_START")
    mcp = StdioMCPClient()
    await mcp.connect()
    _crumb("MCP_CONNECT_DONE")
    log.info("MCP connected")

    # Only activate AI if the API key is present
    ai_validator = None
    if config.ai.enabled and os.environ.get("ANTHROPIC_API_KEY"):
        ai_validator = AIValidator(config.ai)
        log.info("AI validator enabled (model=%s, max_calls/day=%d)",
                 config.ai.model, config.ai.max_calls_per_day)
    elif config.ai.enabled:
        log.warning("ai.enabled=true but ANTHROPIC_API_KEY is not set — running without AI")

    bot = TradingBot(config=config, mcp=mcp, supabase_logger=db_logger,
                     ai_validator=ai_validator)
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_shutdown(*_):
        loop.call_soon_threadsafe(shutdown.set)

    try:
        loop.add_signal_handler(signal.SIGINT, shutdown.set)
        loop.add_signal_handler(signal.SIGTERM, shutdown.set)
    except (NotImplementedError, AttributeError):
        signal.signal(signal.SIGINT, _request_shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _request_shutdown)

    db_logger.update_bot_status("RUNNING")

    # Reconcile the positions table with live MT5 state before the first cycle,
    # pruning rows for positions that closed while the bot was down.
    try:
        await bot.reconcile_positions_table()
    except Exception:
        log.exception("Startup position reconciliation failed — continuing")

    consecutive_failures = 0
    needs_reconnect = False

    try:
        while not shutdown.is_set():

            # ── reconnect loop ─────────────────────────────────────────────
            if needs_reconnect:
                wait = min(10 * consecutive_failures, 120)
                log.warning("MCP reconnect attempt in %ds (failure #%d) …",
                            wait, consecutive_failures)
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=float(wait))
                except asyncio.TimeoutError:
                    pass
                if shutdown.is_set():
                    break
                try:
                    await mcp.close()
                except Exception:
                    pass
                try:
                    await mcp.connect()
                    log.info("MCP reconnected successfully")
                    consecutive_failures = 0
                    needs_reconnect = False
                    db_logger.update_bot_status("RUNNING")
                except Exception as re:
                    log.error("Reconnect failed: %s — will retry", re)
                continue  # go back to top: either shutdown or retry reconnect

            # ── normal cycle ───────────────────────────────────────────────
            try:
                await bot.run_cycle()
                consecutive_failures = 0
            except Exception as e:
                consecutive_failures += 1
                log.exception("Cycle failed (#%d)", consecutive_failures)
                db_logger.update_bot_status("ERROR", error=str(e))

                if _looks_like_mcp_failure(e):
                    needs_reconnect = True
                    continue  # skip the 60s wait, go straight to reconnect

                if consecutive_failures >= 10:
                    log.critical("10 consecutive failures — shutting down")
                    break

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                pass
    finally:
        db_logger.update_bot_status("STOPPED")
        await mcp.close()
        log.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
