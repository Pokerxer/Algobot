import asyncio
import logging
import os
import signal
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).parent / ".env")

from src.ai.validator import AIValidator
from src.bot import TradingBot
from src.config.loader import load_config
from src.db.supabase_client import SupabaseLogger
from src.mcp_client.client import StdioMCPClient

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


def _looks_like_mcp_failure(exc: Exception) -> bool:
    msg = f"{type(exc).__name__} {exc}"
    return any(tag in msg for tag in _MCP_RECONNECT_ERRORS)


async def main():
    config = load_config(Path("config/settings.yaml"))
    supabase = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )
    db_logger = SupabaseLogger(supabase)

    mcp = StdioMCPClient()
    await mcp.connect()
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
