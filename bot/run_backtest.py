"""Fetch MT5 H1 data and run the full backtest across all instruments."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import pandas as pd

from main import _SupabaseRest
from src.mcp_client.client import StdioMCPClient
from src.config.loader import load_config
from src.config.schema import AppConfig
from backtesting.runner import BacktestRunner
from backtesting.data_provider import CSVDataProvider

DATA_DIR = Path("backtest_data")
DATA_DIR.mkdir(exist_ok=True)

INSTRUMENTS = [
    "EURUSDm", "GBPUSDm", "GBPJPYm", "USDJPYm",
    "XAUUSDm", "XAGUSDm",
    "US500m", "US30m", "USTECm",
    "BTCUSDm", "ETHUSDm",
]
BARS = 2000   # ~3 months of H1


async def fetch_all(mcp):
    for sym in INSTRUMENTS:
        csv_path = DATA_DIR / f"{sym}.csv"
        print(f"Fetching {sym} ({BARS} H1 bars)...", end=" ", flush=True)
        try:
            bars = await mcp.call_tool("get_rates", {
                "symbol": sym, "timeframe": "H1", "count": BARS,
            })
            df = pd.DataFrame(bars)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.rename(columns={"tick_volume": "volume"})
            df = df[["time", "open", "high", "low", "close", "volume"]]
            df = df.sort_values("time")
            df.to_csv(csv_path, index=False)
            print(f"OK ({len(df)} bars, {df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()})")
        except Exception as e:
            print(f"FAILED: {e}")


def run_backtests():
    cfg = load_config(Path("config/settings.yaml"))
    dp = CSVDataProvider(DATA_DIR)

    print(f"\n{'='*72}")
    print(f"BACKTEST  |  balance=${cfg.account.starting_balance}  risk={cfg.account.risk_per_trade_pct}%")
    print(f"{'='*72}")
    print(f"{'Symbol':12} {'Trades':>7} {'Win%':>7} {'PnL':>10} {'PFactor':>9} {'Sharpe':>8} {'MaxDD':>8}")
    print(f"{'-'*72}")

    total_pnl = 0
    all_trades = []

    for sym in INSTRUMENTS:
        csv_path = DATA_DIR / f"{sym}.csv"
        if not csv_path.exists():
            print(f"{sym:12} {'NO DATA':>7}")
            continue
        try:
            runner = BacktestRunner(cfg, dp)
            result = runner.run(sym, timeframe="H1")
            pnl = result.final_balance - cfg.account.starting_balance
            total_pnl += pnl
            n = len(result.trades)
            wr = result.metrics.get("win_rate", 0) * 100
            pf = result.metrics.get("profit_factor", 0)
            sh = result.metrics.get("sharpe", 0)
            dd = result.metrics.get("max_drawdown", 0) * 100
            all_trades.extend(result.trades)
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            print(f"{sym:12} {n:>7} {wr:>6.1f}% {pnl_str:>10} {pf:>9.2f} {sh:>8.2f} {dd:>7.1f}%")
        except Exception as e:
            print(f"{sym:12} ERROR: {e}")

    print(f"{'='*72}")
    pnl_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
    print(f"{'TOTAL':12} {len(all_trades):>7} trades  net={pnl_str}")

    # Per-strategy breakdown
    if all_trades:
        print(f"\n{'--- By strategy ---'}")
        by_strat: dict = {}
        for t in all_trades:
            s = t.strategy or "unknown"
            by_strat.setdefault(s, []).append(t.pnl)
        for strat, pnls in sorted(by_strat.items()):
            wins = sum(1 for p in pnls if p > 0)
            total = sum(pnls)
            print(f"  {strat:20} {len(pnls):>4} trades  {wins/len(pnls)*100:>5.1f}% win  "
                  f"net={'+' if total>=0 else ''}{total:.2f}")


async def main():
    mcp = StdioMCPClient()
    await mcp.connect()
    try:
        print("Connected to MT5. Fetching H1 data...\n")
        await fetch_all(mcp)
    finally:
        await mcp.close()

    print("\nRunning backtests...\n")
    run_backtests()


asyncio.run(main())
