# London Session Breakout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `LondonBreakoutStrategy` as a time-gated parallel strategy that emits BUY/SELL signals when price closes beyond the Asian session range (00:00–07:00 UTC) during the London open window (07:00–10:00 UTC).

**Architecture:** Option A — parallel strategy list. `LondonBreakoutStrategy` implements `BaseStrategy` and gates itself by UTC time extracted from the DataFrame's `DatetimeIndex`. `TradingBot` dispatches it via a new `_parallel_strategies: list[BaseStrategy]` after the existing regime-keyed strategy pass. No changes to `Regime` enum or `RegimeDetector`.

**Tech Stack:** Python 3.11, pandas, pydantic v2, pytest, pytest-asyncio

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `bot/src/config/schema.py` | Modify | Add `LondonBreakoutStrategyConfig`; extend `StrategyConfig` |
| `bot/config/settings.yaml` | Modify | Add `strategy.london_breakout` block |
| `bot/src/strategies/london_breakout.py` | Create | `LondonBreakoutStrategy` class + `_pip_size` helper |
| `bot/src/bot.py` | Modify | `_parallel_strategies` in `__init__`; second pass in `run_cycle` |
| `bot/tests/test_config_schema.py` | Modify | Two new tests for `LondonBreakoutStrategyConfig` |
| `bot/tests/test_london_breakout_strategy.py` | Create | 11 unit tests covering all strategy logic |
| `bot/tests/test_bot_orchestrator.py` | Modify | One new test for `_parallel_strategies` |

---

## Task 1: Config schema + settings.yaml

**Files:**
- Modify: `bot/src/config/schema.py`
- Modify: `bot/config/settings.yaml`
- Modify: `bot/tests/test_config_schema.py`

- [ ] **Step 1: Write the failing tests**

Open `bot/tests/test_config_schema.py`. Update the import line at the top to add the new class:

```python
from src.config.schema import AppConfig, AccountConfig, RegimeConfig, MeanReversionStrategyConfig, LondonBreakoutStrategyConfig
```

Append to the end of the file:

```python
def test_london_breakout_config_defaults():
    cfg = LondonBreakoutStrategyConfig()
    assert cfg.session_start_utc == 7
    assert cfg.session_end_utc == 10
    assert cfg.tp_multiplier == 1.5
    assert cfg.min_range_pips == 10.0
    assert "EURUSDm" in cfg.pairs


def test_strategy_config_has_london_breakout_field():
    from src.config.schema import StrategyConfig
    cfg = StrategyConfig()
    assert hasattr(cfg, "london_breakout")
    assert cfg.london_breakout.session_start_utc == 7
```

- [ ] **Step 2: Run to verify they fail**

```
cd bot && pytest tests/test_config_schema.py::test_london_breakout_config_defaults tests/test_config_schema.py::test_strategy_config_has_london_breakout_field -v
```

Expected: `ImportError: cannot import name 'LondonBreakoutStrategyConfig'`

- [ ] **Step 3: Add LondonBreakoutStrategyConfig to schema.py**

Open `bot/src/config/schema.py`. After the `MeanReversionStrategyConfig` class, insert:

```python
class LondonBreakoutStrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_start_utc: int = 7
    session_end_utc: int = 10
    tp_multiplier: float = 1.5
    min_range_pips: float = 10.0
    pairs: list[str] = Field(default_factory=lambda: [
        "EURUSDm", "GBPUSDm", "USDJPYm"
    ])
```

Replace the existing `StrategyConfig` class with:

```python
class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    momentum: MomentumStrategyConfig = MomentumStrategyConfig()
    mean_reversion: MeanReversionStrategyConfig = MeanReversionStrategyConfig()
    london_breakout: LondonBreakoutStrategyConfig = LondonBreakoutStrategyConfig()
```

- [ ] **Step 4: Run to verify the new tests pass**

```
cd bot && pytest tests/test_config_schema.py -v
```

Expected: all 7 tests PASSED

- [ ] **Step 5: Add london_breakout block to settings.yaml**

Open `bot/config/settings.yaml`. After the `mean_reversion:` block (before `ai:`), add:

```yaml
  london_breakout:
    session_start_utc: 7
    session_end_utc: 10
    tp_multiplier: 1.5
    min_range_pips: 10.0
    pairs:
      - EURUSDm
      - GBPUSDm
      - USDJPYm
```

- [ ] **Step 6: Verify config loader accepts the new YAML**

```
cd bot && pytest tests/test_config_loader.py -v
```

Expected: all PASSED (the loader parses `AppConfig` including the new field)

- [ ] **Step 7: Commit**

```bash
git add bot/src/config/schema.py bot/config/settings.yaml bot/tests/test_config_schema.py
git commit -m "feat(config): add LondonBreakoutStrategyConfig"
```

---

## Task 2: LondonBreakoutStrategy class

**Files:**
- Create: `bot/src/strategies/london_breakout.py`
- Create: `bot/tests/test_london_breakout_strategy.py`

- [ ] **Step 1: Write all failing tests**

Create `bot/tests/test_london_breakout_strategy.py`:

```python
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.config.schema import LondonBreakoutStrategyConfig
from src.models.regime import Regime, RegimeState
from src.strategies.london_breakout import LondonBreakoutStrategy


def _regime(instrument: str = "EURUSDm") -> RegimeState:
    return RegimeState(instrument=instrument, regime=Regime.RANGING, confidence=0.75)


def _make_df(
    last_bar_hour: int,
    last_close: float,
    asian_high: float = 1.0850,
    asian_low: float = 1.0800,
) -> pd.DataFrame:
    """M15 DataFrame: 28 Asian bars (00:00–06:45 UTC) + 1 London bar at last_bar_hour."""
    today = datetime(2026, 5, 31, tzinfo=timezone.utc)
    asian_times = pd.date_range(
        start=today.replace(hour=0, minute=0),
        periods=28,
        freq="15min",
        tz=timezone.utc,
    )
    n = len(asian_times)
    asian_df = pd.DataFrame(
        {
            "open": np.full(n, 1.0825),
            "high": np.full(n, asian_high),
            "low": np.full(n, asian_low),
            "close": np.full(n, 1.0825),
        },
        index=asian_times,
    )
    london_time = today.replace(hour=last_bar_hour, minute=0)
    london_df = pd.DataFrame(
        {
            "open": [1.0840],
            "high": [last_close + 0.0002],
            "low": [last_close - 0.0002],
            "close": [last_close],
        },
        index=pd.DatetimeIndex([london_time], tz=timezone.utc),
    )
    return pd.concat([asian_df, london_df])


def _strat() -> LondonBreakoutStrategy:
    return LondonBreakoutStrategy(LondonBreakoutStrategyConfig())


# ── Time gate ──────────────────────────────────────────────────────────────────

def test_no_signal_before_london_open():
    df = _make_df(last_bar_hour=6, last_close=1.0860)
    assert _strat().generate_signal(df, _regime()) is None


def test_no_signal_at_or_after_window_close():
    df = _make_df(last_bar_hour=10, last_close=1.0860)
    assert _strat().generate_signal(df, _regime()) is None


# ── Price position ─────────────────────────────────────────────────────────────

def test_no_signal_when_price_inside_range():
    df = _make_df(last_bar_hour=8, last_close=1.0825)  # inside [1.0800, 1.0850]
    assert _strat().generate_signal(df, _regime()) is None


def test_buy_signal_on_upside_break():
    df = _make_df(last_bar_hour=8, last_close=1.0860)  # above 1.0850
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert sig.direction.value == "BUY"


def test_sell_signal_on_downside_break():
    df = _make_df(last_bar_hour=8, last_close=1.0790)  # below 1.0800
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert sig.direction.value == "SELL"


# ── Noise filter ───────────────────────────────────────────────────────────────

def test_no_signal_range_too_tight():
    # asian_high − asian_low = 1.0803 − 1.0800 = 3 pips < min_range_pips=10
    df = _make_df(last_bar_hour=8, last_close=1.0810,
                  asian_high=1.0803, asian_low=1.0800)
    assert _strat().generate_signal(df, _regime()) is None


# ── Stop loss placement ────────────────────────────────────────────────────────

def test_stop_loss_at_asian_low_on_buy():
    df = _make_df(last_bar_hour=8, last_close=1.0860)
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert abs(sig.stop_loss - 1.0800) < 1e-6


def test_stop_loss_at_asian_high_on_sell():
    df = _make_df(last_bar_hour=8, last_close=1.0790)
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert abs(sig.stop_loss - 1.0850) < 1e-6


# ── Take profit ────────────────────────────────────────────────────────────────

def test_tp_is_range_times_multiplier_on_buy():
    asian_high, asian_low, close = 1.0850, 1.0800, 1.0860
    df = _make_df(last_bar_hour=8, last_close=close,
                  asian_high=asian_high, asian_low=asian_low)
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    expected = close + (asian_high - asian_low) * 1.5
    assert abs(sig.take_profit - expected) < 1e-6


# ── Meta ───────────────────────────────────────────────────────────────────────

def test_strategy_name():
    assert _strat().name == "london_breakout"


def test_jpy_pip_size():
    from src.strategies.london_breakout import _pip_size
    assert _pip_size("USDJPYm") == 0.01
    assert _pip_size("EURUSDm") == 0.0001
```

- [ ] **Step 2: Run to verify all fail**

```
cd bot && pytest tests/test_london_breakout_strategy.py -v
```

Expected: 11 FAILED with `ModuleNotFoundError: No module named 'src.strategies.london_breakout'`

- [ ] **Step 3: Create the strategy file**

Create `bot/src/strategies/london_breakout.py`:

```python
from datetime import timezone
from typing import Optional

import pandas as pd

from src.config.schema import LondonBreakoutStrategyConfig
from src.models.regime import RegimeState
from src.models.signal import Direction, Signal
from src.strategies.base import BaseStrategy


def _pip_size(instrument: str) -> float:
    return 0.01 if "JPY" in instrument.upper() else 0.0001


class LondonBreakoutStrategy(BaseStrategy):
    name = "london_breakout"

    def __init__(self, config: LondonBreakoutStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if not isinstance(df.index, pd.DatetimeIndex):
            return None

        last_ts = df.index[-1]
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        else:
            last_ts = last_ts.astimezone(timezone.utc)

        hour = last_ts.hour
        if hour < self._cfg.session_start_utc or hour >= self._cfg.session_end_utc:
            return None

        today = last_ts.date()
        asian_mask = (df.index.date == today) & (df.index.hour < self._cfg.session_start_utc)
        df_asian = df[asian_mask]

        if len(df_asian) < 3:
            return None

        asian_high = float(df_asian["high"].max())
        asian_low  = float(df_asian["low"].min())

        pip = _pip_size(regime.instrument)
        if (asian_high - asian_low) / pip < self._cfg.min_range_pips:
            return None

        close      = float(df["close"].iloc[-1])
        range_size = asian_high - asian_low

        if close > asian_high:
            return Signal(
                instrument=regime.instrument,
                direction=Direction.BUY,
                entry_price=close,
                stop_loss=asian_low,
                take_profit=close + range_size * self._cfg.tp_multiplier,
                confidence=regime.confidence,
                regime=regime.regime,
                strategy=self.name,
            )

        if close < asian_low:
            return Signal(
                instrument=regime.instrument,
                direction=Direction.SELL,
                entry_price=close,
                stop_loss=asian_high,
                take_profit=close - range_size * self._cfg.tp_multiplier,
                confidence=regime.confidence,
                regime=regime.regime,
                strategy=self.name,
            )

        return None
```

- [ ] **Step 4: Run to verify all pass**

```
cd bot && pytest tests/test_london_breakout_strategy.py -v
```

Expected: 11 PASSED

- [ ] **Step 5: Commit**

```bash
git add bot/src/strategies/london_breakout.py bot/tests/test_london_breakout_strategy.py
git commit -m "feat(strategy): add LondonBreakoutStrategy with Asian range detection"
```

---

## Task 3: Wire LondonBreakoutStrategy into TradingBot

**Files:**
- Modify: `bot/src/bot.py`
- Modify: `bot/tests/test_bot_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Open `bot/tests/test_bot_orchestrator.py`. Append to the end of the file:

```python
def test_parallel_strategies_contains_london_breakout():
    from src.strategies.london_breakout import LondonBreakoutStrategy
    bot = TradingBot(config=_config(), mcp=MagicMock(), supabase_logger=MagicMock())
    assert hasattr(bot, "_parallel_strategies")
    assert any(isinstance(s, LondonBreakoutStrategy) for s in bot._parallel_strategies)
```

- [ ] **Step 2: Run to verify it fails**

```
cd bot && pytest tests/test_bot_orchestrator.py::test_parallel_strategies_contains_london_breakout -v
```

Expected: FAILED with `AttributeError: 'TradingBot' object has no attribute '_parallel_strategies'`

- [ ] **Step 3: Add import and _parallel_strategies to TradingBot.__init__**

Open `bot/src/bot.py`. At the top with the other strategy imports (around line 23–24), add:

```python
from src.strategies.london_breakout import LondonBreakoutStrategy
```

In `TradingBot.__init__`, after the `self._strategies` dict definition (after the closing `}` of the dict, around line 52), add:

```python
        self._parallel_strategies: list[BaseStrategy] = [
            LondonBreakoutStrategy(config.strategy.london_breakout),
        ]
```

- [ ] **Step 4: Run to verify it passes**

```
cd bot && pytest tests/test_bot_orchestrator.py::test_parallel_strategies_contains_london_breakout -v
```

Expected: PASSED

- [ ] **Step 5: Add the London Breakout pass to run_cycle**

Open `bot/src/bot.py`. At the end of `run_cycle()`, immediately after the closing `}` / dedent of the `for choice in selected:` block (before the next `async def` method), add the following block at 8-space indent (same level as the `for choice in selected:` line):

```python
        # ── London Breakout parallel pass ──────────────────────────────────────
        lb_pairs = set(self._cfg.strategy.london_breakout.pairs)
        lb_states = [s for s in regime_states if s.instrument in lb_pairs]
        for state in lb_states:
            lb_df = await self._fetcher.fetch_ohlcv(
                state.instrument, self._cfg.timeframes.entry, bars=200,
            )
            if lb_df is None or lb_df.empty:
                continue
            for strat in self._parallel_strategies:
                signal = strat.generate_signal(lb_df, state)
                if signal is None:
                    continue
                if self._is_duplicate_signal(signal):
                    log.debug("LB duplicate suppressed: %s %s",
                              signal.instrument, signal.direction.value)
                    continue
                self._record_signal_time(signal)
                decision = self._risk.evaluate(
                    signal=signal,
                    balance=balance,
                    open_positions=self._portfolio.positions,
                    daily_pnl=self._daily_pnl(),
                    correlation_matrix=corr_matrix,
                    spread_ratio=spread_ratios.get(state.instrument, 1.0),
                )
                if not decision.approved:
                    log.info("LB signal rejected for %s: %s",
                             state.instrument, decision.reason)
                    self._db.log_signal(signal, executed=False)
                    continue
                ai_decision = None
                if self._ai is not None:
                    ai_decision = await self._ai.validate(signal, state, balance)
                    if ai_decision.action == "VETO":
                        log.info("AI vetoed LB %s: %s",
                                 state.instrument, ai_decision.reasoning)
                        self._db.log_signal(
                            signal, executed=False,
                            ai_decision="VETO", ai_reasoning=ai_decision.reasoning,
                        )
                        continue
                    if ai_decision.action == "MODIFY":
                        if ai_decision.stop_loss is not None:
                            signal = signal.model_copy(
                                update={"stop_loss": ai_decision.stop_loss}
                            )
                        if ai_decision.take_profit is not None:
                            signal = signal.model_copy(
                                update={"take_profit": ai_decision.take_profit}
                            )
                result = await self._execution.place_order(signal, decision.lot_size)
                self._db.log_signal(
                    signal,
                    executed=(result.status == "FILLED"),
                    ai_decision=ai_decision.action if ai_decision else None,
                    ai_reasoning=ai_decision.reasoning if ai_decision else None,
                )
                if result.status == "FILLED":
                    log.info(
                        "LB order placed  %s  #%s  SL=%.5f  TP=%.5f",
                        state.instrument, result.ticket,
                        signal.stop_loss, signal.take_profit,
                    )
                else:
                    log.warning("LB order REJECTED for %s: %s",
                                state.instrument, result.error)
```

- [ ] **Step 6: Run the full test suite — verify no regressions**

```
cd bot && pytest -v
```

Expected: all tests PASSED (existing + new)

- [ ] **Step 7: Commit**

```bash
git add bot/src/bot.py bot/tests/test_bot_orchestrator.py
git commit -m "feat(bot): wire LondonBreakoutStrategy as parallel strategy in run_cycle"
```

---

## Done

After Task 3 is committed, the London Session Breakout strategy is fully live:

- Fires during 07:00–10:00 UTC on EURUSDm, GBPUSDm, USDJPYm
- Stops and targets are anchored to the Asian range, not ATR
- Passes through the same AI validation, risk check, and execution path as all other signals
- Pair list and session window are configurable in `settings.yaml` without code changes
