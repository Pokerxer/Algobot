# Master Trend Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the TradingView "Master Trend Strategy v1.1" (MT signals + Rejection orders, R-based breakeven/trailing) into the Algobot bot, restricted to USTECm and US30m on M15.

**Architecture:** A new stateless `MasterTrendStrategy` implements `BaseStrategy.generate_signal`, computing all indicators from the M15 dataframe and rebuilding rejection trend-line state deterministically each call. It runs as an independent parallel pass in `bot.py` (mirroring the London Breakout pass) alongside existing routing. Exits use broker-side fixed %-TP/SL plus a dedicated `master_trend` branch in position management that replicates Pine's 2R breakeven and 3R/50-pip trailing.

**Tech Stack:** Python 3, pandas, pandas_ta, pydantic, pytest.

## Global Constraints

- Instruments: **USTECm, US30m only**. Timeframe: **M15** (`timeframes.entry`).
- Settings (verbatim from screenshots): MT `tp_pct=0.5`, `sl_pct=0.1`; Rejections `tp_pct=0.3`, `sl_pct=0.1`; `be_ratio=2.0`; `trail_start_rr=3.0`; `trail_step_pips=50.0`; `line_extension_bars=25`; long+short enabled; EMA750 proximity filter, pyramiding, time filter all **off/omitted**.
- Strategy `name` string is `"master_trend"` for both MT and Rejection signals (drives the exit branch).
- EMA750 requires ≥ 750 bars; strategy returns `None` below that. Parallel pass fetches **900** M15 bars.
- Follow existing patterns: `pandas_ta` for EMA/RSI/SMA, `Signal`/`RegimeState` models, `extra="forbid"` on config, tests in the style of `tests/test_london_breakout_strategy.py`.

---

### Task 1: Config schema + settings

**Files:**
- Modify: `bot/src/config/schema.py`
- Modify: `bot/config/settings.yaml`
- Test: `bot/tests/test_config_schema.py` (append)

**Interfaces:**
- Produces: `MasterTrendStrategyConfig` with fields `pairs: list[str]`, `enable_long: bool`, `enable_short: bool`, `enable_mt_signals: bool`, `enable_rejections: bool`, `tp_pct_mt: float`, `sl_pct_mt: float`, `tp_pct_rej: float`, `sl_pct_rej: float`, `line_extension_bars: int`, `be_ratio: float`, `trail_start_rr: float`, `trail_step_pips: float`, `pip_size_fallback: float`, `time_filter_enabled: bool`. Reachable as `config.strategy.master_trend`.

- [ ] **Step 1: Write the failing test**

Append to `bot/tests/test_config_schema.py`:

```python
def test_master_trend_config_defaults():
    from src.config.schema import MasterTrendStrategyConfig, StrategyConfig
    cfg = MasterTrendStrategyConfig()
    assert cfg.pairs == ["USTECm", "US30m"]
    assert cfg.tp_pct_mt == 0.5 and cfg.sl_pct_mt == 0.1
    assert cfg.tp_pct_rej == 0.3 and cfg.sl_pct_rej == 0.1
    assert cfg.be_ratio == 2.0 and cfg.trail_start_rr == 3.0
    assert cfg.trail_step_pips == 50.0 and cfg.line_extension_bars == 25
    assert cfg.enable_long and cfg.enable_short
    assert cfg.enable_mt_signals and cfg.enable_rejections
    assert StrategyConfig().master_trend.pairs == ["USTECm", "US30m"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bot && python -m pytest tests/test_config_schema.py::test_master_trend_config_defaults -v`
Expected: FAIL with `ImportError` / `cannot import name 'MasterTrendStrategyConfig'`.

- [ ] **Step 3: Add the config class**

In `bot/src/config/schema.py`, add after `LondonBreakoutStrategyConfig`:

```python
class MasterTrendStrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairs: list[str] = Field(default_factory=lambda: ["USTECm", "US30m"])
    enable_long: bool = True
    enable_short: bool = True
    enable_mt_signals: bool = True
    enable_rejections: bool = True
    tp_pct_mt: float = 0.5
    sl_pct_mt: float = 0.1
    tp_pct_rej: float = 0.3
    sl_pct_rej: float = 0.1
    line_extension_bars: int = 25
    be_ratio: float = 2.0
    trail_start_rr: float = 3.0
    trail_step_pips: float = 50.0
    pip_size_fallback: float = 1.0   # index point value when symbol mintick is unavailable
    time_filter_enabled: bool = False
```

Then add the field to `StrategyConfig`:

```python
class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    momentum: MomentumStrategyConfig = MomentumStrategyConfig()
    mean_reversion: MeanReversionStrategyConfig = MeanReversionStrategyConfig()
    london_breakout: LondonBreakoutStrategyConfig = LondonBreakoutStrategyConfig()
    master_trend: MasterTrendStrategyConfig = MasterTrendStrategyConfig()
```

- [ ] **Step 4: Add the settings.yaml block**

In `bot/config/settings.yaml`, under `strategy:` (after the `london_breakout:` block), add:

```yaml
  master_trend:
    pairs: [USTECm, US30m]
    enable_long: true
    enable_short: true
    enable_mt_signals: true
    enable_rejections: true
    tp_pct_mt: 0.5
    sl_pct_mt: 0.1
    tp_pct_rej: 0.3
    sl_pct_rej: 0.1
    line_extension_bars: 25
    be_ratio: 2.0
    trail_start_rr: 3.0
    trail_step_pips: 50.0
    pip_size_fallback: 1.0
    time_filter_enabled: false
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd bot && python -m pytest tests/test_config_schema.py -v && python -m pytest tests/test_config_loader.py -v`
Expected: PASS (config schema test passes; loader still parses settings.yaml).

- [ ] **Step 6: Commit**

```bash
git add bot/src/config/schema.py bot/config/settings.yaml bot/tests/test_config_schema.py
git commit -m "feat(config): add MasterTrendStrategyConfig for USTEC/US30 M15"
```

---

### Task 2: Indicator helpers

**Files:**
- Create: `bot/src/strategies/master_trend.py`
- Test: `bot/tests/test_master_trend_indicators.py`

**Interfaces:**
- Produces (module-level functions in `master_trend.py`):
  - `_stoch_k(df: pd.DataFrame, length: int = 10, smooth: int = 3) -> pd.Series`
  - `_session_vwap(df: pd.DataFrame) -> pd.Series`
  - `_bull_engulf(df: pd.DataFrame) -> pd.Series` (bool)
  - `_bear_engulf(df: pd.DataFrame) -> pd.Series` (bool)

- [ ] **Step 1: Write the failing test**

Create `bot/tests/test_master_trend_indicators.py`:

```python
import numpy as np
import pandas as pd
from datetime import timezone

from src.strategies.master_trend import (
    _stoch_k, _session_vwap, _bull_engulf, _bear_engulf,
)


def _df(o, h, l, c, vol=None, tz=True):
    n = len(c)
    idx = pd.date_range("2026-07-01", periods=n, freq="15min",
                        tz=timezone.utc if tz else None)
    data = {"open": o, "high": h, "low": l, "close": c}
    if vol is not None:
        data["volume"] = vol
    return pd.DataFrame(data, index=idx)


def test_stoch_k_matches_manual():
    # 12 bars; last bar close at the high of a rising range => %K near 100
    c = np.linspace(100, 111, 12)
    df = _df(c, c + 1, c - 1, c)
    k = _stoch_k(df, length=10, smooth=3)
    assert 90.0 <= float(k.iloc[-1]) <= 100.0
    assert k.iloc[:2].isna().all()  # warm-up NaNs before rolling windows fill


def test_session_vwap_resets_each_utc_day():
    # Day 1: two bars hl2=10; Day 2 first bar hl2=20 => vwap resets to 20 not blended
    idx = pd.DatetimeIndex([
        "2026-07-01 23:30", "2026-07-01 23:45", "2026-07-02 00:00",
    ], tz=timezone.utc)
    df = pd.DataFrame({
        "open": [10, 10, 20], "high": [11, 11, 21],
        "low": [9, 9, 19], "close": [10, 10, 20],
        "volume": [1, 1, 1],
    }, index=idx)
    v = _session_vwap(df)
    assert abs(float(v.iloc[-1]) - 20.0) < 1e-9


def test_bull_engulf_detects_pattern():
    # bar[-2] bearish (open 10 -> close 9); bar[-1] bullish engulf (open 9 -> close 10.5)
    df = _df([10, 10, 9], [10.1, 10.1, 10.6], [8.9, 8.9, 8.9], [10, 9, 10.5])
    assert bool(_bull_engulf(df).iloc[-1]) is True
    assert bool(_bear_engulf(df).iloc[-1]) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bot && python -m pytest tests/test_master_trend_indicators.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.strategies.master_trend'`.

- [ ] **Step 3: Write the helpers**

Create `bot/src/strategies/master_trend.py`:

```python
"""Master Trend Strategy — Pine 'Master Trend Strategy v1.1' port.

MT signal entries + stateful Rejection entries for USTECm / US30m on M15.
Chart visuals from the original script are intentionally not ported.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import pandas_ta as ta

from src.config.schema import MasterTrendStrategyConfig
from src.models.regime import RegimeState
from src.models.signal import Direction, Signal
from src.strategies.base import BaseStrategy

_MIN_BARS = 750


def _stoch_k(df: pd.DataFrame, length: int = 10, smooth: int = 3) -> pd.Series:
    """Pine ta.sma(ta.stoch(close, high, low, length), smooth)."""
    ll = df["low"].rolling(length).min()
    hh = df["high"].rolling(length).max()
    rng = (hh - ll).replace(0.0, float("nan"))
    raw = 100.0 * (df["close"] - ll) / rng
    return raw.rolling(smooth).mean()


def _session_vwap(df: pd.DataFrame) -> pd.Series:
    """hl2-weighted VWAP anchored to the UTC calendar day (Pine ta.vwap(hl2)).

    Falls back to equal weighting (running hl2 mean) when volume is missing or
    all-zero — MT5 tick volume is sometimes unavailable.
    """
    idx = df.index
    days = (idx.tz_convert("UTC").date if getattr(idx, "tz", None) is not None
            else idx.date)
    grp = pd.Series(days, index=df.index)
    hl2 = (df["high"] + df["low"]) / 2.0
    if "volume" in df.columns and float(df["volume"].sum()) > 0.0:
        vol = df["volume"].astype(float)
    else:
        vol = pd.Series(1.0, index=df.index)
    pv = (hl2 * vol).groupby(grp).cumsum()
    vv = vol.groupby(grp).cumsum()
    return pv / vv


def _bull_engulf(df: pd.DataFrame) -> pd.Series:
    o, c = df["open"], df["close"]
    o1, c1 = o.shift(1), c.shift(1)
    prev_bear = c1 < o1
    cur_bull = c > o
    return (prev_bear & cur_bull & (o <= c1) & (c >= o1)).fillna(False)


def _bear_engulf(df: pd.DataFrame) -> pd.Series:
    o, c = df["open"], df["close"]
    o1, c1 = o.shift(1), c.shift(1)
    prev_bull = c1 > o1
    cur_bear = c < o
    return (prev_bull & cur_bear & (o >= c1) & (c <= o1)).fillna(False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd bot && python -m pytest tests/test_master_trend_indicators.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add bot/src/strategies/master_trend.py bot/tests/test_master_trend_indicators.py
git commit -m "feat(strategy): Master Trend indicator helpers (stoch, session vwap, engulfing)"
```

---

### Task 3: MT signal entries

**Files:**
- Modify: `bot/src/strategies/master_trend.py`
- Test: `bot/tests/test_master_trend_strategy.py`

**Interfaces:**
- Consumes: helpers from Task 2; `MasterTrendStrategyConfig`.
- Produces:
  - `MasterTrendStrategy(config: MasterTrendStrategyConfig)` with `name = "master_trend"` and `generate_signal(df, regime) -> Optional[Signal]`.
  - Module function `_compute(df: pd.DataFrame) -> pd.DataFrame` adding columns `bull_sig`, `bear_sig`, `ema750` to a copy of `df`.
  - Method `_signal(self, regime, direction, close, tp_pct, sl_pct) -> Signal`.

- [ ] **Step 1: Write the failing test**

Create `bot/tests/test_master_trend_strategy.py`:

```python
import numpy as np
import pandas as pd
from datetime import timezone

from src.config.schema import MasterTrendStrategyConfig
from src.models.regime import Regime, RegimeState
from src.strategies.master_trend import MasterTrendStrategy


def _regime(instrument="USTECm"):
    return RegimeState(instrument=instrument, regime=Regime.TRENDING_UP, confidence=0.7)


def _strat(**over):
    return MasterTrendStrategy(MasterTrendStrategyConfig(**over))


def _uptrend_df(n=820, start=15000.0, step=3.0):
    """Long, steady uptrend so every EMA (incl. 750) is below price and rising.
    The final two bars force ema4-cross-above-ema5 by dipping then surging."""
    idx = pd.date_range("2026-06-01", periods=n, freq="15min", tz=timezone.utc)
    close = start + np.arange(n) * step
    close[-2] -= step * 4          # dip: pulls ema4 toward ema5
    close[-1] = close[-2] + step * 12  # surge: ema4 crosses above ema5, big bull close
    high = close + 2.0
    low = close - 2.0
    open_ = np.r_[close[0], close[:-1]]
    vol = np.full(n, 100.0)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def test_returns_none_below_min_bars():
    df = _uptrend_df(n=700)
    assert _strat().generate_signal(df, _regime()) is None


def test_mt_bull_signal_emits_buy_with_pct_tp_sl():
    df = _uptrend_df()
    sig = _strat().generate_signal(df, _regime())
    assert sig is not None
    assert sig.direction.value == "BUY"
    assert sig.strategy == "master_trend"
    close = float(df["close"].iloc[-1])
    assert abs(sig.take_profit - close * 1.005) < 1e-6   # tp_pct_mt 0.5%
    assert abs(sig.stop_loss - close * 0.999) < 1e-6     # sl_pct_mt 0.1%


def test_enable_long_false_suppresses_buy():
    df = _uptrend_df()
    assert _strat(enable_long=False, enable_rejections=False).generate_signal(df, _regime()) is None


def test_strategy_name():
    assert _strat().name == "master_trend"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bot && python -m pytest tests/test_master_trend_strategy.py -v`
Expected: FAIL with `ImportError: cannot import name 'MasterTrendStrategy'`.

- [ ] **Step 3: Add `_compute` and the strategy class**

Append to `bot/src/strategies/master_trend.py`:

```python
def _compute(df: pd.DataFrame) -> pd.DataFrame:
    """Return df copy with bull_sig / bear_sig / ema750 columns."""
    out = df.copy()
    close = out["close"]
    rsi = ta.rsi(close, length=14)
    ema4 = ta.ema(close, length=4)
    ema5 = ta.ema(close, length=5)
    ema21 = ta.ema(close, length=21)
    sma50 = ta.sma(close, length=50)
    ema55 = ta.ema(close, length=55)
    ema89 = ta.ema(close, length=89)
    ema750 = ta.ema(close, length=750)

    cross_up = (ema4 > ema5) & (ema4.shift(1) <= ema5.shift(1))
    cross_dn = (ema4 < ema5) & (ema4.shift(1) >= ema5.shift(1))

    stok = _stoch_k(out)
    ema89_bull_bo = (close > ema89) & (close.shift(1) <= ema89.shift(1))
    ema89_bear_bo = (close < ema89) & (close.shift(1) >= ema89.shift(1))
    vwap = _session_vwap(out)
    vwap_up = (close > vwap) & (close.shift(1) <= vwap.shift(1))
    vwap_dn = (close < vwap) & (close.shift(1) >= vwap.shift(1))
    bull_valid = _bull_engulf(out) & (close > ema750)
    bear_valid = _bear_engulf(out) & (close < ema750)

    conf_bull = (stok > 52) | ema89_bull_bo | vwap_up | bull_valid
    conf_bear = (stok < 48) | ema89_bear_bo | vwap_dn | bear_valid

    out["ema750"] = ema750
    out["bull_sig"] = (
        cross_up & (rsi > 50)
        & (close > ema21) & (close > sma50) & (close > ema55)
        & (close > ema89) & (close > ema750) & conf_bull
    ).fillna(False)
    out["bear_sig"] = (
        cross_dn & (rsi < 50)
        & (close < ema21) & (close < sma50) & (close < ema55)
        & (close < ema89) & (close < ema750) & conf_bear
    ).fillna(False)
    return out


class MasterTrendStrategy(BaseStrategy):
    name = "master_trend"

    def __init__(self, config: MasterTrendStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if df is None or len(df) < _MIN_BARS:
            return None
        c = _compute(df)
        if bool(pd.isna(c["ema750"].iloc[-1])):
            return None

        close = float(c["close"].iloc[-1])
        cfg = self._cfg

        # ── MT signal entries (evaluated first, matching Pine ordering) ──
        if cfg.enable_mt_signals:
            if bool(c["bull_sig"].iloc[-1]) and cfg.enable_long:
                return self._signal(regime, Direction.BUY, close,
                                    cfg.tp_pct_mt, cfg.sl_pct_mt)
            if bool(c["bear_sig"].iloc[-1]) and cfg.enable_short:
                return self._signal(regime, Direction.SELL, close,
                                    cfg.tp_pct_mt, cfg.sl_pct_mt)

        # ── Rejection entries (added in Task 4) ──
        if cfg.enable_rejections:
            rej = self._rejection(c, regime)
            if rej is not None:
                return rej
        return None

    def _rejection(self, c: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        return None  # implemented in Task 4

    def _signal(self, regime: RegimeState, direction: Direction, close: float,
                tp_pct: float, sl_pct: float) -> Signal:
        if direction == Direction.BUY:
            tp = close * (1 + tp_pct / 100)
            sl = close * (1 - sl_pct / 100)
        else:
            tp = close * (1 - tp_pct / 100)
            sl = close * (1 + sl_pct / 100)
        return Signal(
            instrument=regime.instrument, direction=direction,
            entry_price=close, stop_loss=sl, take_profit=tp,
            confidence=regime.confidence, regime=regime.regime, strategy=self.name,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd bot && python -m pytest tests/test_master_trend_strategy.py -v`
Expected: PASS (4 tests). If `test_mt_bull_signal_emits_buy_with_pct_tp_sl` fails because the synthetic frame did not trip a confirmation branch, widen the final surge (`step * 12` → larger) until `bull_sig` fires — the confirmation is satisfied by the large bull close crossing EMA89.

- [ ] **Step 5: Commit**

```bash
git add bot/src/strategies/master_trend.py bot/tests/test_master_trend_strategy.py
git commit -m "feat(strategy): Master Trend MT signal entries with %-based TP/SL"
```

---

### Task 4: Rejection entries

**Files:**
- Modify: `bot/src/strategies/master_trend.py` (replace `_rejection` stub)
- Test: `bot/tests/test_master_trend_strategy.py` (append)

**Interfaces:**
- Consumes: `_compute` output columns `bull_sig`, `bear_sig`, `ema750`; `self._cfg.line_extension_bars`, `tp_pct_rej`, `sl_pct_rej`, `enable_long`, `enable_short`; `self._signal`.
- Produces: `MasterTrendStrategy._rejection(c: pd.DataFrame, regime) -> Optional[Signal]`.

- [ ] **Step 1: Write the failing test**

Append to `bot/tests/test_master_trend_strategy.py`:

```python
from src.strategies.master_trend import _compute


def test_bull_rejection_emits_buy():
    # Build an uptrend that fires an MT bull signal, then a later bar that wicks
    # down to that signal bar's open and closes back above it (and above ema750).
    df = _uptrend_df()
    c_pre = _compute(df)
    # find the last MT bull signal bar in the valid window (last 25 bars)
    sig_positions = [i for i in range(len(c_pre) - 26, len(c_pre) - 1)
                     if bool(c_pre["bull_sig"].iloc[i])]
    assert sig_positions, "fixture must contain an MT bull signal in the window"
    j = sig_positions[-1]
    line_price = float(df["open"].iloc[j])
    # append a rejection bar: low pierces the line, close recovers above it
    new_idx = df.index[-1] + pd.Timedelta("15min")
    close = line_price + 5.0
    rej_bar = pd.DataFrame(
        {"open": [line_price + 1], "high": [close + 2],
         "low": [line_price - 3], "close": [close], "volume": [100.0]},
        index=pd.DatetimeIndex([new_idx], tz=df.index.tz),
    )
    df2 = pd.concat([df, rej_bar])
    sig = _strat(enable_mt_signals=False).generate_signal(df2, _regime())
    assert sig is not None
    assert sig.direction.value == "BUY"
    assert abs(sig.take_profit - close * 1.003) < 1e-6   # tp_pct_rej 0.3%


def test_no_rejection_when_close_below_line():
    df = _uptrend_df()
    new_idx = df.index[-1] + pd.Timedelta("15min")
    # a bar that closes below every recent signal-bar open => no bull rejection
    low_close = float(df["open"].iloc[-30]) - 50.0
    rej_bar = pd.DataFrame(
        {"open": [low_close + 1], "high": [low_close + 2],
         "low": [low_close - 2], "close": [low_close], "volume": [100.0]},
        index=pd.DatetimeIndex([new_idx], tz=df.index.tz),
    )
    df2 = pd.concat([df, rej_bar])
    assert _strat(enable_mt_signals=False).generate_signal(df2, _regime()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bot && python -m pytest tests/test_master_trend_strategy.py -k rejection -v`
Expected: FAIL (`_rejection` stub returns None → `test_bull_rejection_emits_buy` fails on `sig is not None`).

- [ ] **Step 3: Implement `_rejection`**

Replace the `_rejection` stub in `bot/src/strategies/master_trend.py`:

```python
    def _rejection(self, c: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        cfg = self._cfg
        last = len(c) - 1
        low = float(c["low"].iloc[last])
        high = float(c["high"].iloc[last])
        close = float(c["close"].iloc[last])
        ema750 = float(c["ema750"].iloc[last])
        ext = cfg.line_extension_bars

        opens = c["open"].to_numpy()
        bull = c["bull_sig"].to_numpy()
        bear = c["bear_sig"].to_numpy()

        # Iterate candidate line-origin bars newest-first (Pine order), within the
        # active window (start_bar < last <= start_bar + extension).
        first = max(0, last - ext)
        for j in range(last - 1, first - 1, -1):
            if not (bull[j] or bear[j]):
                continue
            line_price = float(opens[j])
            if (bull[j] and cfg.enable_long
                    and low <= line_price < close and close > ema750):
                return self._signal(regime, Direction.BUY, close,
                                    cfg.tp_pct_rej, cfg.sl_pct_rej)
            if (bear[j] and cfg.enable_short
                    and high >= line_price > close and close < ema750):
                return self._signal(regime, Direction.SELL, close,
                                    cfg.tp_pct_rej, cfg.sl_pct_rej)
        return None
```

Note: Pine's rejection condition is `low <= line and close > line` (bull); the `line_price < close` form above is equivalent and also guards against the degenerate `close == line`. Any MT-signal bar (bull or bear) draws a line; the rejection *direction* keys off the signal type that drew the line, matching the fixture. The bull and bear checks are independent, so a bear line still yields a bear rejection.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd bot && python -m pytest tests/test_master_trend_strategy.py -v`
Expected: PASS (all MT + rejection tests).

- [ ] **Step 5: Commit**

```bash
git add bot/src/strategies/master_trend.py bot/tests/test_master_trend_strategy.py
git commit -m "feat(strategy): Master Trend rejection entries (stateful line rebuild)"
```

---

### Task 5: R-based breakeven + trailing exit branch

**Files:**
- Modify: `bot/src/bot.py` (add `_master_trend_trail`, per-ticket caches, branch in `_manage_positions`)
- Test: `bot/tests/test_master_trend_exits.py`

**Interfaces:**
- Consumes: `Position` (`entry_price`, `stop_loss`, `direction`, `strategy`, `ticket`), `config.strategy.master_trend`.
- Produces on `TradingBot`:
  - `self._mt_r_dist: dict[int, float]`, `self._mt_high_water: dict[int, float]` (init in `__init__`).
  - `_master_trend_trail(self, pos: Position, bid: float, ask: float, pip_size: float) -> Optional[float]` — returns a new SL or `None`.

- [ ] **Step 1: Write the failing test**

Create `bot/tests/test_master_trend_exits.py`:

```python
from datetime import datetime, timezone

from src.models.position import Position
from src.models.regime import Regime
from src.models.signal import Direction


def _pos(entry, sl, direction=Direction.BUY, ticket=1):
    return Position(
        ticket=ticket, instrument="US30m", direction=direction,
        entry_price=entry, current_price=entry, volume=1.0, profit=0.0,
        stop_loss=sl, take_profit=None,
        opened_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        strategy="master_trend", regime=Regime.TRENDING_UP,
    )


def _bot():
    # Build a TradingBot without __init__; only config + caches are used here.
    from src.bot import TradingBot
    from src.config.schema import AppConfig, AccountConfig
    cfg = AppConfig(account=AccountConfig(starting_balance=1500), instruments=["US30m"])
    bot = TradingBot.__new__(TradingBot)
    bot._cfg = cfg
    bot._mt_r_dist = {}
    bot._mt_high_water = {}
    return bot


def test_breakeven_moves_sl_to_entry_at_2r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40
    pos = _pos(entry, sl)                    # BUY
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 2R = 40080 => SL should move up to entry
    new_sl = bot._master_trend_trail(pos, bid=40080.0, ask=40080.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - entry) < 1e-6


def test_trailing_follows_50_pips_after_3r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40, pip_size 1.0
    pos = _pos(entry, sl)
    pos = pos.model_copy(update={"stop_loss": entry})  # already at BE
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 3R = 40120 => trail to high_water - 50*1.0 = 40070
    new_sl = bot._master_trend_trail(pos, bid=40120.0, ask=40120.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - 40070.0) < 1e-6


def test_no_loosening_below_2r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0
    pos = _pos(entry, sl)
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 1R only => no BE, no trail
    assert bot._master_trend_trail(pos, bid=40040.0, ask=40040.0, pip_size=1.0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bot && python -m pytest tests/test_master_trend_exits.py -v`
Expected: FAIL with `AttributeError: 'TradingBot' object has no attribute '_master_trend_trail'`.

- [ ] **Step 3: Add caches and the trail method**

In `bot/src/bot.py` `__init__`, alongside the other per-session caches (near `self._close_attempted`), add:

```python
        # Master Trend exit state (session-scoped, keyed by ticket)
        self._mt_r_dist: dict[int, float] = {}      # original |entry - SL| distance (R)
        self._mt_high_water: dict[int, float] = {}  # best price seen since fill
```

Add the method (place it next to `_trail_sl`):

```python
    def _master_trend_trail(self, pos: Position, bid: float, ask: float,
                            pip_size: float) -> Optional[float]:
        """Pine-faithful exit for master_trend positions: SL->entry at be_ratio*R,
        then trail trail_step_pips behind high-water once trail_start_rr*R reached."""
        cfg = self._cfg.strategy.master_trend
        r = self._mt_r_dist.get(pos.ticket)
        if r is None:
            # Recover R from the still-original SL (skip once SL is already at BE).
            if pos.stop_loss and abs(pos.stop_loss - pos.entry_price) > 1e-9:
                r = abs(pos.entry_price - pos.stop_loss)
                self._mt_r_dist[pos.ticket] = r
            else:
                return None
        if r <= 0:
            return None

        entry = pos.entry_price
        step = cfg.trail_step_pips * pip_size

        if pos.direction.value == "BUY":
            price = bid
            hw = max(self._mt_high_water.get(pos.ticket, price), price)
            self._mt_high_water[pos.ticket] = hw
            profit = price - entry
            if profit >= cfg.trail_start_rr * r:
                trail = hw - step
                return trail if pos.stop_loss is None or trail > pos.stop_loss else None
            if profit >= cfg.be_ratio * r:
                return entry if pos.stop_loss is None or entry > pos.stop_loss else None
        else:
            price = ask
            hw = min(self._mt_high_water.get(pos.ticket, price), price)
            self._mt_high_water[pos.ticket] = hw
            profit = entry - price
            if profit >= cfg.trail_start_rr * r:
                trail = hw + step
                return trail if pos.stop_loss is None or trail < pos.stop_loss else None
            if profit >= cfg.be_ratio * r:
                return entry if pos.stop_loss is None or entry < pos.stop_loss else None
        return None
```

- [ ] **Step 4: Wire the branch into `_manage_positions`**

In `_manage_positions`, replace the trailing block that currently reads:

```python
            new_sl = self._trail_sl(pos, atr, bid, ask)
            if new_sl is not None:
                log.info("Trailing SL  #%d %s: %.5f → %.5f  (ATR=%.5f)",
                         pos.ticket, pos.instrument, pos.stop_loss, new_sl, atr)
                await self._execution.modify_position(pos.ticket, stop_loss=new_sl)
```

with:

```python
            if pos.strategy == "master_trend":
                point = float(price_info.get("point",
                              self._cfg.strategy.master_trend.pip_size_fallback))
                new_sl = self._master_trend_trail(pos, bid, ask, point)
            else:
                new_sl = self._trail_sl(pos, atr, bid, ask)
            if new_sl is not None:
                log.info("Trailing SL  #%d %s: %.5f → %.5f",
                         pos.ticket, pos.instrument, pos.stop_loss or 0.0, new_sl)
                await self._execution.modify_position(pos.ticket, stop_loss=new_sl)
```

Note: `price_info` is already defined earlier in the same loop (`price_info = live_prices.get(pos.instrument, {})`); reuse it, don't refetch.

Also prune closed tickets: at the top of `_manage_positions`, after `positions = self._portfolio.positions`, add:

```python
        _open = {p.ticket for p in positions}
        for _t in list(self._mt_r_dist):
            if _t not in _open:
                self._mt_r_dist.pop(_t, None)
                self._mt_high_water.pop(_t, None)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd bot && python -m pytest tests/test_master_trend_exits.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add bot/src/bot.py bot/tests/test_master_trend_exits.py
git commit -m "feat(bot): R-based breakeven+trailing exit branch for master_trend"
```

---

### Task 6: Parallel pass wiring

**Files:**
- Modify: `bot/src/bot.py` (import, instantiate, add parallel pass)

**Interfaces:**
- Consumes: `MasterTrendStrategy`, `config.strategy.master_trend`, existing `_fetcher`, `_risk`, `_execution`, `_db`, `_is_duplicate_signal`, `_record_signal_time`, `_in_session`, `_mt_r_dist`.

- [ ] **Step 1: Import and instantiate**

In `bot/src/bot.py`, add the import near the other strategy imports:

```python
from src.strategies.master_trend import MasterTrendStrategy
```

In `__init__`, after `self._smc_gold = SMCGoldStrategy()`:

```python
        self._master_trend = MasterTrendStrategy(config.strategy.master_trend)
```

- [ ] **Step 2: Add the parallel pass**

In `run_cycle`, immediately after the London Breakout parallel pass (before the deferred Supabase writes at `self._db.update_bot_status(...)`), insert:

```python
        # ── Master Trend parallel pass (USTECm / US30m, M15) ────────────────────
        mt_cfg = self._cfg.strategy.master_trend
        mt_pairs = [s for s in regime_states if s.instrument in set(mt_cfg.pairs)]
        for state in mt_pairs:
            if not self._in_session(state.instrument):
                continue
            mt_df = await self._fetcher.fetch_ohlcv(
                state.instrument, self._cfg.timeframes.entry, bars=900,
            )
            if mt_df is None or mt_df.empty:
                continue
            signal = self._master_trend.generate_signal(mt_df, state)
            if signal is None:
                continue
            if self._is_duplicate_signal(signal):
                log.debug("MT duplicate suppressed: %s %s",
                          signal.instrument, signal.direction.value)
                continue
            self._record_signal_time(signal)
            decision = self._risk.evaluate(
                signal=signal, balance=balance,
                open_positions=self._portfolio.positions,
                daily_pnl=self._daily_pnl(),
                correlation_matrix=corr_matrix,
                spread_ratio=spread_ratios.get(state.instrument, 1.0),
            )
            if not decision.approved:
                log.info("MT signal rejected for %s: %s",
                         state.instrument, decision.reason)
                self._db.log_signal(signal, executed=False, rejection_reason=decision.reason)
                continue
            ai_decision = None
            if self._ai is not None:
                ai_decision = await self._ai.validate(signal, state, balance)
                if ai_decision.action == "VETO":
                    log.info("AI vetoed MT %s: %s", state.instrument, ai_decision.reasoning)
                    self._db.log_signal(signal, executed=False,
                                        ai_decision="VETO", ai_reasoning=ai_decision.reasoning)
                    continue
                if ai_decision.action == "MODIFY":
                    if ai_decision.stop_loss is not None:
                        signal = signal.model_copy(update={"stop_loss": ai_decision.stop_loss})
                    if ai_decision.take_profit is not None:
                        signal = signal.model_copy(update={"take_profit": ai_decision.take_profit})
                    log.info("AI modified MT SL/TP for %s: %s",
                             state.instrument, ai_decision.reasoning)
            result = await self._execution.place_order(signal, decision.lot_size)
            self._db.log_signal(
                signal, executed=(result.status == "FILLED"),
                ai_decision=ai_decision.action if ai_decision else None,
                ai_reasoning=ai_decision.reasoning if ai_decision else None,
            )
            if result.status == "FILLED":
                # Seed the exit-management R cache from the entry-time SL distance.
                self._mt_r_dist[result.ticket] = abs(signal.entry_price - signal.stop_loss)
                log.info("MT order placed  %s  #%s  SL=%.5f  TP=%.5f",
                         state.instrument, result.ticket, signal.stop_loss, signal.take_profit)
            else:
                log.warning("MT order REJECTED for %s: %s", state.instrument, result.error)
```

- [ ] **Step 3: Run the bot orchestrator tests**

Run: `cd bot && python -m pytest tests/test_bot_orchestrator.py tests/test_main.py -v`
Expected: PASS (existing orchestrator tests unaffected; bot constructs and runs a cycle).

- [ ] **Step 4: Run the entire suite**

Run: `cd bot && python -m pytest -q`
Expected: PASS (all tests green, including the new Master Trend tests).

- [ ] **Step 5: Commit**

```bash
git add bot/src/bot.py
git commit -m "feat(bot): wire Master Trend parallel pass for USTEC/US30 (M15)"
```

---

## Notes for the implementer

- **Fixture tuning (Tasks 3–4):** the synthetic uptrend must satisfy *all* MT gate conditions (price above every EMA incl. the 750, RSI>50, ema4-cross-above-ema5, plus one confirmation). If `bull_sig` never fires, increase the final-bar surge or the total bar count; do not weaken the strategy conditions to fit the test.
- **`point` field:** MT5's `get_symbol_info` returns the tick size under `point` on this bot's MCP client. If a run shows the trailing step is off by a power of ten, confirm the field name against a live `get_symbol_info` payload and adjust the `.get("point", ...)` key — the `pip_size_fallback` config exists precisely so this can be corrected without code changes.
- **No behavior change** to momentum / mean-reversion / London Breakout / SMC passes is intended; if any of their tests change, that is a regression to investigate, not to paper over.
```