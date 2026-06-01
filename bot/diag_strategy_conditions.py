"""Per-condition breakdown of why generate_signal() returns None.

For each instrument that reaches its strategy, recompute the same indicators the
strategy uses and report every entry condition with its value, flagging the first
one that fails (the short-circuit point). Read-only; places no orders.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import pandas_ta as ta  # noqa: E402
from main import _SupabaseRest  # noqa: E402
from src.config.loader import load_config  # noqa: E402
from src.db.supabase_client import SupabaseLogger  # noqa: E402
from src.mcp_client.client import StdioMCPClient  # noqa: E402
from src.bot import TradingBot  # noqa: E402
from src.models.regime import Regime  # noqa: E402
from src.regime.indicators import compute_atr, compute_adx  # noqa: E402
from src.strategies.momentum import _adx_is_rising, _SLOPE_MIN_ATR  # noqa: E402

logging.basicConfig(level=logging.ERROR)
YN = lambda b: "PASS" if b else "fail"


def mr_breakdown(df, c):
    rsi = ta.rsi(df["close"], length=c.rsi_period)
    bb = ta.bbands(df["close"], length=20, std=c.bb_std)
    bbl = next(x for x in bb.columns if x.startswith("BBL"))
    bbu = next(x for x in bb.columns if x.startswith("BBU"))
    close = float(df["close"].iloc[-1]); lower = float(bb[bbl].iloc[-1]); upper = float(bb[bbu].iloc[-1])
    rsi_now = float(rsi.iloc[-1]); pctb = (close - lower) / (upper - lower) if upper > lower else 0.0
    lower_touch = close <= lower; upper_touch = close >= upper
    lines = [
        f"    close={close:.5f}  band=[{lower:.5f} .. {upper:.5f}]  %B={pctb:.2f}  (0=lower band, 1=upper band)",
        f"    [{YN(lower_touch)}] price at/below LOWER band (BUY setup)   close<=lower",
        f"    [{YN(upper_touch)}] price at/above UPPER band (SELL setup)  close>=upper",
        f"    rsi={rsi_now:.1f}  (BUY needs <{c.rsi_oversold} ; SELL needs >{c.rsi_overbought})",
    ]
    if not (lower_touch or upper_touch):
        lines.append("    => FIRST FAIL: price is mid-band, not touching either band — no setup")
    elif lower_touch and rsi_now >= c.rsi_oversold:
        lines.append(f"    => FIRST FAIL: at lower band but RSI {rsi_now:.1f} not < {c.rsi_oversold}")
    elif upper_touch and rsi_now <= c.rsi_overbought:
        lines.append(f"    => FIRST FAIL: at upper band but RSI {rsi_now:.1f} not > {c.rsi_overbought}")
    else:
        lines.append("    => band+RSI met; would then check double-touch + divergence")
    return "\n".join(lines)


def mom_breakdown(df, c, regime):
    fast = ta.ema(df["close"], length=c.fast_ema); slow = ta.ema(df["close"], length=c.slow_ema)
    atr = compute_atr(df, 14); rsi = ta.rsi(df["close"], length=c.rsi_period)
    close = float(df["close"].iloc[-1]); prev = float(df["close"].iloc[-2]); prev2 = float(df["close"].iloc[-3])
    fast_now = float(fast.iloc[-1]); slow_now = float(slow.iloc[-1]); atr_now = float(atr.iloc[-1]); rsi_now = float(rsi.iloc[-1])
    slow_10 = float(slow.iloc[-10]) if len(slow) > 10 else slow_now
    slope_atr = (slow_now - slow_10) / atr_now if atr_now > 0 else 0.0
    try:
        adx_rising = _adx_is_rising(compute_adx(df, 14)["adx"])
    except ValueError:
        adx_rising = True
    down = regime.regime == Regime.TRENDING_DOWN
    ema_ok = fast_now < slow_now if down else fast_now > slow_now
    slope_ok = slope_atr < -_SLOPE_MIN_ATR if down else slope_atr > _SLOPE_MIN_ATR
    rsi_ok = rsi_now < c.rsi_midline if down else rsi_now > c.rsi_midline
    if down:
        touched = float(df["high"].iloc[-2]) >= fast_now * 0.999
        bouncing = (close < prev) and (prev < prev2)
    else:
        touched = float(df["low"].iloc[-2]) <= fast_now * 1.001
        bouncing = (close > prev) and (prev > prev2)
    checks = [
        (adx_rising, "ADX rising (trend strengthening)"),
        (ema_ok,    f"fast/slow EMA aligned ({'fast<slow' if down else 'fast>slow'}): {fast_now:.5f} vs {slow_now:.5f}"),
        (slope_ok,  f"slow-EMA slope steep enough: slope_atr={slope_atr:.3f} (need {'<' if down else '>'} {('-' if down else '')}{_SLOPE_MIN_ATR})"),
        (rsi_ok,    f"RSI past midline: rsi={rsi_now:.1f} (need {'<' if down else '>'} {c.rsi_midline})"),
        (touched,   "price pulled back to fast EMA (last bar wick touched it)"),
        (bouncing,  f"two consecutive {'down' if down else 'up'} closes (pullback bounce)"),
    ]
    lines = [f"    close={close:.5f}  fast_ema={fast_now:.5f}  slow_ema={slow_now:.5f}  atr={atr_now:.5f}"]
    first = None
    for ok, label in checks:
        lines.append(f"    [{YN(ok)}] {label}")
        if not ok and first is None:
            first = label
    lines.append(f"    => FIRST FAIL: {first}" if first else "    => all core checks PASS (would emit a signal)")
    return "\n".join(lines)


async def main():
    cfg = load_config(Path("config/settings.yaml"))
    db = SupabaseLogger(_SupabaseRest(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]))
    mcp = StdioMCPClient(); await mcp.connect()
    bot = TradingBot(config=cfg, mcp=mcp, supabase_logger=db, ai_validator=None)
    try:
        await bot._portfolio.sync()
        print(f"\n=== Strategy condition breakdown @ {datetime.now(timezone.utc):%H:%M} UTC ===")
        for inst in cfg.instruments:
            df = await bot._fetcher.fetch_ohlcv(inst, cfg.timeframes.regime, bars=500)
            state = bot._regime.classify(inst, df)
            edf = await bot._fetcher.fetch_ohlcv(inst, cfg.timeframes.entry, bars=200)
            if state.regime in (Regime.RANGING, Regime.CHOPPY):
                print(f"\n{inst}  regime={state.regime.name}  strategy=mean_reversion")
                print(mr_breakdown(edf, cfg.strategy.mean_reversion))
            elif state.regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
                print(f"\n{inst}  regime={state.regime.name}  strategy=momentum")
                print(mom_breakdown(edf, cfg.strategy.momentum, state))
    finally:
        await mcp.close()


asyncio.run(main())
