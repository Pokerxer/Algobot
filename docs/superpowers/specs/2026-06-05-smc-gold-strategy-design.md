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
- Enters BUY only (long-bias preserved — no SELL entries)
- Uses Order Block + liquidity sweep as entry trigger
- Targets buy-side liquidity (equal highs / external range highs) as TP
- Falls back to 4×ATR if no liquidity pool is found
- Fires only during London or NY open kill zones

## Non-goals (YAGNI)

- No SELL entries on XAU
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

All conditions evaluated on M15 OHLCV data. All must pass:

### Condition 1: Kill zone active
Current UTC hour must be in `[(7, 10), (12, 16)]` (London open, NY open).
Uses existing `in_kill_zone()` from `src/indicators/order_blocks.py`.

### Condition 2: Bullish OB at current price
`price_at_bullish_ob(df, close, instrument="XAUUSDm")` returns True.
Uses existing OB wrapper with XAU swing_length=20, tolerance=0.003.

### Condition 3: Liquidity sweep confirmed
`price_at_bullish_ob` returns True/False but not the OB coordinates. The sweep check needs the OB bottom. Implementation: call `_compute_obs(df, swing_length=20)` directly (internal helper from `order_blocks.py`) to get the nearest bullish OB's `Bottom` value, then:
```
prev_bar.low <= OB_bottom            # swept below (stop-hunt below equal lows)
current_bar.close > OB_bottom        # recovered back above OB
```
This is the ICT "stop hunt and reverse" — institutions grab stops below equal lows / OB support, then reverse. The OB condition (Condition 2) still filters first; the sweep check refines timing.

### Condition 4: D1 structure bullish
Resample M15 df to D1, compute 50-EMA. `close > D1_EMA50`.
Uses existing `_ema_aligned` helper pattern.

If all four pass → generate BUY signal.

## Take-Profit

Primary: compute `smc.liquidity(df, swing_highs_lows(df, swing_length=10))`.
Find nearest **buy-side liquidity pool** (level above current close where equal highs or significant swing highs cluster). Use that level as TP.

Fallback: if no buy-side liquidity found within `5 × ATR` above entry, use `entry + 4 × ATR`.

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
| `bot/src/bot.py` | Add `_SMC_INSTRUMENTS`, SMC-specific pass in `run_cycle` |
| `bot/tests/test_smc_gold_strategy.py` | New — unit tests |
