"""Run the backtest against existing CSV files (no MT5 connection needed)."""
import os
import sys
sys.path.insert(0, ".")
os.environ.setdefault("SUPABASE_URL", "http://dummy")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "dummy")

# WMI shim — this host's WMI service is wedged and deadlocks pandas import.
# Must raise OSError so platform.py falls back to registry/getwindowsversion().
import platform as _platform
def _wmi_query_disabled(*_args, **_kwargs):
    raise OSError("WMI disabled")
_platform._wmi_query = _wmi_query_disabled  # type: ignore

from pathlib import Path
from backtesting.runner import BacktestRunner
from backtesting.data_provider import CSVDataProvider
from src.config.loader import load_config

DATA_DIR = Path("backtest_data")
START = "2025-12-09T00:00:00+00:00"
INSTRUMENTS = [
    "EURUSDm", "GBPUSDm", "GBPJPYm", "USDJPYm",
    "XAUUSDm", "XAGUSDm", "US500m", "US30m", "USTECm",
    "BTCUSDm", "ETHUSDm",
]

cfg = load_config(Path("config/settings.yaml"))
dp = CSVDataProvider(DATA_DIR)

print("=" * 76)
print(f"BACKTEST  6-month window (2025-12-09 to present)")
print(f"balance=${cfg.account.starting_balance}  risk={cfg.account.risk_per_trade_pct}%")
print("=" * 76)
print(f"{'Symbol':12} {'Trades':>7} {'Win%':>7} {'PnL':>10} {'PFactor':>9} {'Sharpe':>8} {'MaxDD':>8}")
print("-" * 76)

total_pnl = 0.0
all_trades = []

for sym in INSTRUMENTS:
    try:
        runner = BacktestRunner(cfg, dp)
        result = runner.run(sym, timeframe="H1", start=START)
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
        import traceback
        traceback.print_exc()
        print(f"{sym:12} ERROR: {e}")

print("=" * 76)
pnl_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
print(f"{'TOTAL':12} {len(all_trades):>7} trades  net={pnl_str}")

if all_trades:
    print("\n--- By strategy ---")
    by_strat: dict = {}
    for t in all_trades:
        s = t.strategy or "unknown"
        by_strat.setdefault(s, []).append(t.pnl)
    for strat, pnls in sorted(by_strat.items()):
        wins = sum(1 for p in pnls if p > 0)
        total = sum(pnls)
        print(f"  {strat:20} {len(pnls):>4} trades  {wins/len(pnls)*100:>5.1f}% win  "
              f"net={'+' if total >= 0 else ''}{total:.2f}")
