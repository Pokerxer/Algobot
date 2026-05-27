import asyncio
import logging
import os
import signal
from pathlib import Path
from supabase import create_client
from src.ai.validator import AIValidator
from src.bot import TradingBot
from src.config.loader import load_config
from src.db.supabase_client import SupabaseLogger
from src.mcp_client.client import StdioMCPClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("algobot")


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

    ai_validator = AIValidator(config.ai) if config.ai.enabled else None
    bot = TradingBot(config=config, mcp=mcp, supabase_logger=db_logger, ai_validator=ai_validator)
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)

    db_logger.update_bot_status("RUNNING")
    try:
        while not shutdown.is_set():
            try:
                await bot.run_cycle()
            except Exception as e:
                log.exception("Cycle failed")
                db_logger.update_bot_status("ERROR", error=str(e))
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
