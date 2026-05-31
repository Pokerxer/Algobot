# London Session Breakout Strategy — Design Spec

**Date:** 2026-05-31
**Status:** Approved
**Scope:** New `LondonBreakoutStrategy` class + config + TradingBot wiring + tests

---

## Overview

The London Session Breakout strategy marks the high and low of the Asian trading session (00:00–07:00 UTC) and enters a directional trade when price closes beyond that range during the London open window (07:00–10:00 UTC). It complements the existing momentum and mean-reversion strategies by capturing the early-trend phase that neither regime-keyed strategy catches: the moment a range is broken.

---

## Architecture

The strategy uses the existing `BaseStrategy` interface and is dispatched via a new `_parallel_strategies: list[BaseStrategy]` collection in `TradingBot`, separate from the regime-keyed `_strategies` dict. Time-gating and instrument filtering are internal to the strategy and wiring respectively — no changes to `Regime` enum or `RegimeDetector`.

### Files Changed / Created

| Path | Change |
|------|--------|
| `bot/src/strategies/london_breakout.py` | New strategy class |
| `bot/src/config/schema.py` | `LondonBreakoutStrategyConfig` + `StrategyConfig` extension |
| `bot/config/settings.yaml` | New `strategy.london_breakout` block |
| `bot/src/bot.py` | `_parallel_strategies` list + second pass in `run_cycle()` |
| `bot/tests/test_london_breakout_strategy.py` | 7 unit tests |

---

## Strategy Logic (`london_breakout.py`)

### `generate_signal(df, regime) -> Optional[Signal]`

**Step 1 — Time gate**
- Extract current UTC datetime from `df.index[-1]` (last bar timestamp).
- If `utc_hour < session_start_utc` or `utc_hour >= session_end_utc`, return `None`.
- Default window: `session_start_utc=7`, `session_end_utc=10`.

**Step 2 — Asian range computation**
- Filter `df` to rows where `bar.timestamp.date() == today` and `bar.timestamp.hour < session_start_utc`.
- `asian_high = df_asian["high"].max()`
- `asian_low = df_asian["low"].min()`
- If fewer than 3 Asian bars are present, return `None` (insufficient data).

**Step 3 — Noise filter**
- `pip_size` is derived from the instrument name: 0.0001 for 4/5-decimal pairs (EUR, GBP, etc.), 0.01 for JPY pairs (detected by "JPY" in name).
- `range_pips = (asian_high - asian_low) / pip_size`
- If `range_pips < min_range_pips` (default 10), return `None`.

**Step 4 — Breakout detection**
- Uses the **close** of the last bar only (wick touches are rejected).
- `close > asian_high` → BUY
  - `stop_loss = asian_low`
  - `take_profit = close + (asian_high - asian_low) * tp_multiplier`
- `close < asian_low` → SELL
  - `stop_loss = asian_high`
  - `take_profit = close - (asian_high - asian_low) * tp_multiplier`
- `confidence` is set to `regime.confidence` (passes through the regime confidence from the detector).
- `strategy` field on `Signal` = `"london_breakout"`.

### Deduplication

`TradingBot._last_signal_time` already deduplicates signals within a 5-minute window per `(instrument, direction)`. One breakout signal per instrument per London session is the expected cadence.

---

## Config Schema (`schema.py`)

```python
class LondonBreakoutStrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_start_utc: int = 7       # London open hour (UTC, inclusive)
    session_end_utc: int = 10        # Stop taking signals at or after this hour (exclusive)
    tp_multiplier: float = 1.5       # take_profit = entry ± range × tp_multiplier
    min_range_pips: float = 10.0     # Skip if Asian session range < this many pips
    pairs: list[str] = Field(default_factory=lambda: [
        "EURUSDm", "GBPUSDm", "EURGBPm", "USDJPYm"
    ])
```

`StrategyConfig` gains a new field:
```python
london_breakout: LondonBreakoutStrategyConfig = LondonBreakoutStrategyConfig()
```

---

## settings.yaml Addition

```yaml
strategy:
  london_breakout:
    session_start_utc: 7
    session_end_utc: 10
    tp_multiplier: 1.5
    min_range_pips: 10.0
    pairs:
      - EURUSDm
      - GBPUSDm
      - EURGBPm
      - USDJPYm
```

---

## TradingBot Wiring (`bot.py`)

### `__init__`

```python
from src.strategies.london_breakout import LondonBreakoutStrategy
...
self._parallel_strategies: list[BaseStrategy] = [
    LondonBreakoutStrategy(config.strategy.london_breakout),
]
```

### `run_cycle()`

After the existing regime-keyed strategy block, add a second pass:

```python
# First pass: collect per-instrument regime states into a local dict
regime_states: dict[str, RegimeState] = {}
for instrument in selected_instruments:
    df_regime = self._fetcher.fetch(instrument, self._cfg.timeframes.regime)
    if df_regime is not None and not df_regime.empty:
        regime_states[instrument] = self._regime.detect(df_regime)

# ... existing regime-keyed strategy dispatch using regime_states ...

# Second pass: parallel strategies (time-gated, not regime-keyed)
lb_pairs = set(self._cfg.strategy.london_breakout.pairs)
for instrument in selected_instruments:
    if instrument not in lb_pairs:
        continue
    regime_state = regime_states.get(instrument)
    if regime_state is None:
        continue
    df_entry = self._fetcher.fetch(instrument, self._cfg.timeframes.entry)
    if df_entry is None or df_entry.empty:
        continue
    for strat in self._parallel_strategies:
        signal = strat.generate_signal(df_entry, regime_state)
        if signal:
            # same AI validation + risk check + execution path as existing signals
```

The existing regime-keyed dispatch is refactored to populate `regime_states` first, then both the main pass and the parallel pass consume that local dict — no redundant MCP calls.

---

## Tests (`test_london_breakout_strategy.py`)

All tests use a synthetic DataFrame fixture with timestamps set to a fixed date. UTC hour is controlled by setting the last bar's index timestamp.

| Test | Condition | Expected |
|------|-----------|----------|
| `test_no_signal_outside_london_window` | Last bar at 06:59 UTC and at 10:00 UTC | `None` both cases |
| `test_no_signal_when_price_inside_range` | Close between asian_low and asian_high | `None` |
| `test_buy_signal_on_upside_break` | Close > asian_high, hour = 08:00 UTC | `Signal(direction=BUY)` |
| `test_sell_signal_on_downside_break` | Close < asian_low, hour = 08:00 UTC | `Signal(direction=SELL)` |
| `test_no_signal_range_too_tight` | asian_high − asian_low < min_range_pips | `None` |
| `test_stop_loss_at_opposite_band` | BUY breakout | `signal.stop_loss == asian_low` |
| `test_tp_is_range_multiple` | BUY breakout | `signal.take_profit == close + range * 1.5` |

---

## Edge Cases

- **Partial Asian data** (bot started mid-session): return `None` if fewer than 3 Asian bars are available.
- **Weekend / market closed**: `df` will have no bars after Friday close; time gate returns `None`.
- **JPY pip sizing**: detected from instrument name suffix `"JPY"` → pip_size = 0.01, otherwise 0.0001.
- **Both breakout directions on same bar**: impossible (close is a single value); only one direction can fire.
- **Already in position on this instrument**: handled downstream by `RiskManager.check_signal()` — no change needed in strategy.
