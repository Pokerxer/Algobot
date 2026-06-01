"""Read-only signal-pipeline trace.

Mirrors run_cycle()'s gating sequence for every instrument and reports exactly
where each one drops out — including strategy.generate_signal() returning None,
which run_cycle does not log. Places NO orders.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from main import _SupabaseRest  # noqa: E402  (WMI shim + REST adapter)
from src.config.loader import load_config  # noqa: E402
from src.db.supabase_client import SupabaseLogger  # noqa: E402
from src.mcp_client.client import StdioMCPClient  # noqa: E402
from src.bot import TradingBot, _MEAN_REV_ONLY, _MOMENTUM_ONLY  # noqa: E402
from src.models.regime import Regime  # noqa: E402

logging.basicConfig(level=logging.WARNING)  # keep noise down; we print our own trace
TREND = (Regime.TRENDING_UP, Regime.TRENDING_DOWN)


async def evaluate(bot, inst, state, cfg):
    """Return the reason `inst` would be dropped, or the signal it would emit."""
    if not bot._in_session(inst):
        return "DROP: out of session window"
    if inst in _MEAN_REV_ONLY and state.regime in TREND:
        return "DROP: MEAN_REV_ONLY but regime is trending"
    if inst in _MOMENTUM_ONLY and state.regime in (Regime.RANGING, Regime.CHOPPY):
        return f"DROP: MOMENTUM_ONLY but regime is {state.regime.name}"
    allowed = bot._session_allowed_regimes(inst)
    if allowed is not None and state.regime not in allowed:
        names = sorted(r.name for r in allowed) or "(none)"
        return f"DROP: session-regime gate — {state.regime.name} not in {names}"
    if state.regime in TREND:
        direction = "BUY" if state.regime == Regime.TRENDING_UP else "SELL"
        if not await bot._h4_aligned(inst, direction):
            return f"DROP: H4 not aligned ({direction})"
        if not await bot._d1_aligned(inst, direction):
            return f"DROP: D1 not aligned ({direction})"
    strat = bot._strategies.get(state.regime)
    if strat is None:
        return "DROP: no strategy for regime"
    df = await bot._fetcher.fetch_ohlcv(inst, cfg.timeframes.entry, bars=200)
    sig = strat.generate_signal(df, state)
    if sig is None:
        return f"DROP: {type(strat).__name__}.generate_signal -> None (entry conditions unmet)"
    return f"*** SIGNAL {sig.direction.value} conf={sig.confidence:.2f} ({type(strat).__name__})"


async def main():
    cfg = load_config(Path("config/settings.yaml"))
    db = SupabaseLogger(_SupabaseRest(os.environ["SUPABASE_URL"],
                                      os.environ["SUPABASE_SERVICE_KEY"]))
    mcp = StdioMCPClient()
    await mcp.connect()
    bot = TradingBot(config=cfg, mcp=mcp, supabase_logger=db, ai_validator=None)
    try:
        await bot._portfolio.sync()
        hour = datetime.now(timezone.utc).hour
        print(f"\n=== Signal trace @ {hour:02d}:xx UTC ===")

        regime_states = []
        for inst in cfg.instruments:
            df = await bot._fetcher.fetch_ohlcv(inst, cfg.timeframes.regime, bars=500)
            regime_states.append(bot._regime.classify(inst, df))

        spread_ratios = await bot._compute_spread_ratios()
        selected = {c.instrument for c in bot._selector.select(
            regime_states, spread_ratios,
            recent_sharpe=bot._compute_sharpe_by_instrument())}
        print(f"Selector picked (top {cfg.account.max_concurrent_positions}): {sorted(selected)}\n")

        for state in regime_states:
            inst = state.instrument
            tag = "[selected]" if inst in selected else "[not selected]"
            reason = await evaluate(bot, inst, state, cfg)
            print(f"{inst:9s} {state.regime.name:14s} {tag:15s} {reason}")

        # London Breakout parallel pass (its own session check + strategy)
        print("\n--- London Breakout parallel pass ---")
        lb_pairs = set(cfg.strategy.london_breakout.pairs)
        for state in [s for s in regime_states if s.instrument in lb_pairs]:
            inst = state.instrument
            if not bot._in_session(inst):
                print(f"{inst:9s} DROP: out of session"); continue
            df = await bot._fetcher.fetch_ohlcv(inst, cfg.timeframes.entry, bars=200)
            sig = bot._parallel_strategies[0].generate_signal(df, state)
            print(f"{inst:9s} {'SIGNAL ' + sig.direction.value if sig else 'DROP: generate_signal -> None'}")
    finally:
        await mcp.close()


asyncio.run(main())
