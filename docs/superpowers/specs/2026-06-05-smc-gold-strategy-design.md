# SMC Gold Strategy — Design

- **Date:** 2026-06-05
- **Status:** Approved
- **Owner:** jrwal

## Problem

XAUUSDm generates 0 profitable trades with the current strategy stack:
- Standard MR (BB+RSI): 25% win rate → sweep requirement restored → 0 trades
- Momentum SELL: blocked by long-bias (`_LONG_BIAS` frozenset)
- Momentum BUY: rare (TRENDING_UP + D1 + kill zone + slope all required)

Gold's intraday price action follows ICT/SMC logic more reliably than mean-reversion or EMA-based momentum. Institutional players run buy-side liquidity (equal highs) before pushing higher, creating predictable stop-hunt-and-reverse patterns at Order Blocks.

## Goal

A dedicated SMC-only entry model for XAUUSDm that:
- Trades **both directions** based on market structure (OB direction + D1 alignment)
- Uses Order Block + liquidity sweep as entry trigger
- BUY: targets buy-side liquidity (equal highs / external range highs) as TP
- SELL: targets sell-side liquidity (equal lows / external range lows) as TP
- Falls back to 4×ATR if no liquidity pool is found
- Fires only during London or NY open kill zones

## Non-goals (YAGNI)

- No CHoCH computation (adds ~2s latency per bar; OB+sweep is sufficient)
- No London Breakout variant for XAU
- No changes to other instruments

## Architecture

### New file: `bot/src/strategies/smc_gold.py`

`SMCGoldStrategy(BaseStrategy)` — standalone class, no dependency on regime classifier.

```
generate_signal(df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]
```

The strategy ignores `regime.regime` — it uses its own SMC logic regardless of whether the ADX says RANGING or TRENDING. `regime` is passed only for `instrument`, `confidence`, and compliance with `BaseStrategy` interface.

### Integration in `bot.py`

Add `_SMC_INSTRUMENTS: frozenset = frozenset({"XAUUSDm"})`.

In `run_cycle`, before the existing regime-based signal loop, add an SMC-specific pass:

```python
for inst in [i for i in selected_instruments if i in _SMC_INSTRUMENTS]:
    df_m15 = await self._fetcher.fetch_ohlcv(inst, "M15", bars=200)
    state = next(s for s in regime_states if s.instrument == inst)
    signal = self._smc_strategy.generate_signal(df_m15, state)
    if signal: # → risk eval → place order
```

This sidesteps regime routing entirely for XAU.

## Entry Logic

All conditions evaluated on M15 OHLCV data. Strategy evaluates **both BUY and SELL** independently each cycle — whichever OB is nearest and passes all conditions fires first.

### Condition 1: Kill zone active
Current UTC hour must be in `[(7, 10), (12, 16)]` (London open, NY open).
Uses existing `in_kill_zone()` from `src/indicators/order_blocks.py`.

### Condition 2: OB at current price
- **BUY path:** `price_at_bullish_ob(df, close, instrument="XAUUSDm")` → True
- **SELL path:** `price_at_bearish_ob(df, close, instrument="XAUUSDm")` → True

Uses existing OB wrapper with XAU swing_length=20, tolerance=0.003.

### Condition 3: Liquidity sweep confirmed
Call `_compute_obs(df, swing_length=20)` directly to get the OB boundary coordinates, then:

**BUY sweep:**
```
prev_bar.low  <= bullish_OB_bottom   # stop-hunt below equal lows / OB support
current_close >  bullish_OB_bottom   # recovered back above OB
```

**SELL sweep:**
```
prev_bar.high >= bearish_OB_top      # stop-hunt above equal highs / OB resistance
current_close <  bearish_OB_top      # rejected back below OB
```

### Condition 4: D1 structural alignment
Resample M15 df to D1, compute 50-EMA:
- **BUY:** `close > D1_EMA50` (D1 bullish)
- **SELL:** `close < D1_EMA50` (D1 bearish)

This replaces the old long-bias block — market direction is determined by D1 structure, not a hardcoded bias. If D1 is bullish, only BUY setups fire. If D1 is bearish, only SELL setups fire.

If all four pass for a given direction → generate signal in that direction.

## Take-Profit

Compute `smc.liquidity(df, swing_highs_lows(df, swing_length=10))`.

- **BUY TP:** nearest **buy-side liquidity** above entry (equal highs / external swing high). If none found within `5 × ATR`, fallback to `entry + 4 × ATR`.
- **SELL TP:** nearest **sell-side liquidity** below entry (equal lows / external swing low). If none found within `5 × ATR`, fallback to `entry - 4 × ATR`.

The SMC library returns liquidity zones with their price level and type (buy-side / sell-side). Filter for the correct side and take the nearest one above (BUY) or below (SELL) the entry price.

## Stop-Loss

`close - 1.5 × ATR` — same multiplier as the existing `_ATR_STOP_MULTIPLIERS["XAU"]`.
Placed below the OB bottom with room for gold's volatility.

## Risk Management

- Same `RiskManager.evaluate()` call as all other signals
- Same lot sizing (2.5% risk, min stop 800 pips for XAU)
- Logged to `signals` table with `strategy="smc_gold"`

## Testing

- Unit tests for `SMCGoldStrategy.generate_signal()` with fixtures that:
  - Have a bullish OB and sweep → expect BUY signal
  - Have a bullish OB but no sweep → expect None
  - Are outside kill zone hours → expect None
  - D1 is bearish → expect None
- Backtest: route XAUUSDm through `SMCGoldStrategy` and verify trades generate

## File change list

| File | Change |
|---|---|
| `bot/src/strategies/smc_gold.py` | New — SMCGoldStrategy class |
| `bot/src/bot.py` | Add `_SMC_INSTRUMENTS`, SMC-specific pass in `run_cycle`; remove XAUUSDm from `_LONG_BIAS` (D1 alignment now handles direction) |
| `bot/tests/test_smc_gold_strategy.py` | New — unit tests |
