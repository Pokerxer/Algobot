# Why-No-Signal Insight View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dashboard "Insight" page that shows, per instrument, why the bot isn't trading it right now and how close it is to a setup — fed by a per-instrument evaluation the bot persists each cycle.

**Architecture:** The bot computes a per-instrument `Evaluation` each cycle (gates → real strategy verdict → display breakdown) and upserts it to a new `signal_evaluations` table. A standalone evaluator builds the breakdown but calls the *real* `generate_signal()` for the signal/no-setup verdict, so `status` cannot drift from live trading behaviour. A new Next.js page reads the table live.

**Tech Stack:** Python 3.12 (pandas, pandas_ta, pydantic), Supabase/PostgREST, Next.js 16 + React 19 + Tailwind 4, pytest.

---

## File Structure

| File | Responsibility |
|---|---|
| `supabase/migrations/004_signal_evaluations.sql` | new table + RLS + realtime |
| `bot/src/insight/__init__.py` | package marker |
| `bot/src/insight/evaluator.py` | `Evaluation` dataclass + pure `evaluate()` |
| `bot/src/db/supabase_client.py` | `upsert_signal_evaluation()` |
| `bot/src/bot.py` | per-instrument evaluation pass in `run_cycle` |
| `bot/tests/test_evaluator.py` | evaluator unit + status-fidelity tests |
| `dashboard/lib/types.ts` | `SignalEvaluation` interface |
| `dashboard/components/Nav.tsx` | Insight nav link |
| `dashboard/app/insight/page.tsx` | new page |

---

## Task 1: Create the `signal_evaluations` table

**Files:**
- Create: `supabase/migrations/004_signal_evaluations.sql`

- [ ] **Step 1: Write the migration file**

```sql
-- Per-instrument evaluation of why the bot did/didn't signal each cycle.
-- One upserted row per instrument (current state only).
CREATE TABLE IF NOT EXISTS public.signal_evaluations (
  instrument     text PRIMARY KEY,
  regime         text,
  in_session     boolean,
  strategy       text,            -- 'mean_reversion' | 'momentum' | null (gated)
  status         text NOT NULL,   -- 'signal' | 'gated' | 'no_setup'
  reason         text,
  setup_distance numeric,         -- 0..1 proximity to a setup; null when gated
  detail         jsonb,
  updated_at     timestamptz DEFAULT now()
);

ALTER TABLE public.signal_evaluations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_read" ON public.signal_evaluations;
CREATE POLICY "anon_read" ON public.signal_evaluations FOR SELECT TO anon USING (true);
```

- [ ] **Step 2: Apply the migration to the live project**

Apply via the Supabase MCP `apply_migration` tool (project `zgyurumyblqlstqraywb`, name `004_signal_evaluations`) using the SQL above. Then add to realtime (separate statement; ignore "already member" errors):

```sql
ALTER PUBLICATION supabase_realtime ADD TABLE signal_evaluations;
```

- [ ] **Step 3: Verify the table exists**

Run via Supabase MCP `execute_sql`:
```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'signal_evaluations' ORDER BY ordinal_position;
```
Expected: 9 rows (instrument, regime, in_session, strategy, status, reason, setup_distance, detail, updated_at).

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/004_signal_evaluations.sql
git commit -m "feat(db): signal_evaluations table for the insight view"
```

---

## Task 2: The evaluator unit

**Files:**
- Create: `bot/src/insight/__init__.py` (empty)
- Create: `bot/src/insight/evaluator.py`
- Test: `bot/tests/test_evaluator.py`

Context on the real strategies (do not modify them):
- `MeanReversionStrategy.generate_signal(df, regime_state)` returns a `Signal` only when price is at a Bollinger band (`close<=lower` or `close>=upper`) with RSI past `rsi_oversold`/`rsi_overbought`, plus optional double-touch/divergence/expansion filters; else `None`.
- `MomentumStrategy.generate_signal(df, regime_state)` requires (in order) ADX rising, fast/slow EMA alignment, slow-EMA slope ≥ `_SLOPE_MIN_ATR` (0.05) ATR units, RSI past `rsi_midline`, an EMA pullback touch, and two consecutive closes in trend direction; else `None`.
- Helpers available: `from src.strategies.momentum import _adx_is_rising, _SLOPE_MIN_ATR`; `from src.regime.indicators import compute_atr, compute_adx`.
- `RegimeState` has `.instrument`, `.regime` (a `Regime` enum), `.confidence`.

- [ ] **Step 1: Write failing tests**

Create `bot/tests/test_evaluator.py`:
```python
import numpy as np
import pandas as pd
import pytest

from src.config.schema import AppConfig
from src.insight.evaluator import Evaluation, evaluate
from src.models.regime import Regime, RegimeState
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy


def _cfg() -> AppConfig:
    return AppConfig(account={"starting_balance": 500}, instruments=["EURUSD"])


def _walk_df(n=200, price=1.10, seed=7):
    # Mild random walk → valid (non-NaN) indicators and non-degenerate bands,
    # so the evaluator exercises the full breakdown path. (A perfectly flat df
    # gives NaN RSI / collapsed bands and must NOT be used here.)
    rng = np.random.default_rng(seed)
    close = price + np.cumsum(rng.normal(0, 0.0004, n))
    return pd.DataFrame({"open": close, "high": close + 0.0003,
                         "low": close - 0.0003, "close": close,
                         "volume": np.full(n, 1000.0)})


def _state(regime, inst="EURUSD"):
    return RegimeState(instrument=inst, regime=regime, confidence=0.5)


def test_gated_when_out_of_session():
    ev = evaluate("EURUSD", _state(Regime.RANGING), _walk_df(), _cfg(),
                  MeanReversionStrategy(_cfg().strategy.mean_reversion),
                  in_session=False, allowed_regimes=None, mtf_aligned=None,
                  is_mean_rev_only=False, is_momentum_only=False)
    assert ev.status == "gated"
    assert ev.strategy is None
    assert ev.setup_distance is None
    assert "session" in ev.reason.lower()


def test_gated_by_session_regime():
    ev = evaluate("US500m", _state(Regime.CHOPPY, "US500m"), _walk_df(), _cfg(),
                  MeanReversionStrategy(_cfg().strategy.mean_reversion),
                  in_session=True, allowed_regimes=frozenset({Regime.RANGING}),
                  mtf_aligned=None, is_mean_rev_only=False, is_momentum_only=False)
    assert ev.status == "gated"
    assert "session-regime" in ev.reason.lower()


def test_mean_reversion_status_matches_strategy_and_builds_detail():
    # status MUST equal the real strategy verdict (cannot drift); the breakdown
    # is populated regardless of which way the verdict goes.
    strat = MeanReversionStrategy(_cfg().strategy.mean_reversion)
    df, st = _walk_df(), _state(Regime.RANGING)
    ev = evaluate("EURUSD", st, df, _cfg(), strat,
                  in_session=True, allowed_regimes=None, mtf_aligned=None,
                  is_mean_rev_only=False, is_momentum_only=False)
    real = strat.generate_signal(df, st)
    assert (ev.status == "signal") == (real is not None)
    assert ev.strategy == "mean_reversion"
    assert "pct_b" in ev.detail
    assert 0.0 <= ev.setup_distance <= 1.0
    assert ev.reason


def test_momentum_status_matches_strategy_and_builds_detail():
    strat = MomentumStrategy(_cfg().strategy.momentum)
    df, st = _walk_df(seed=3), _state(Regime.TRENDING_DOWN)
    ev = evaluate("BTCUSDm", st, df, _cfg(), strat,
                  in_session=True, allowed_regimes=None, mtf_aligned=True,
                  is_mean_rev_only=False, is_momentum_only=False)
    real = strat.generate_signal(df, st)
    assert (ev.status == "signal") == (real is not None)
    assert "adx_rising" in ev.detail
    assert 0.0 <= ev.setup_distance <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd bot && ./.venv/Scripts/python.exe -m pytest tests/test_evaluator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.insight'`.

- [ ] **Step 3: Create the package marker**

Create empty file `bot/src/insight/__init__.py`.

- [ ] **Step 4: Implement the evaluator**

Create `bot/src/insight/evaluator.py`:
```python
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import pandas_ta as ta

from src.config.schema import AppConfig
from src.models.regime import Regime, RegimeState
from src.regime.indicators import compute_atr, compute_adx
from src.strategies.base import BaseStrategy
from src.strategies.momentum import _adx_is_rising, _SLOPE_MIN_ATR

_TREND = (Regime.TRENDING_UP, Regime.TRENDING_DOWN)


@dataclass
class Evaluation:
    instrument: str
    regime: str
    in_session: bool
    strategy: Optional[str]
    status: str                       # 'signal' | 'gated' | 'no_setup'
    reason: str
    setup_distance: Optional[float]
    detail: dict = field(default_factory=dict)


def _gated(inst, regime, reason) -> Evaluation:
    return Evaluation(inst, regime.value, True, None, "gated", reason, None, {})


def evaluate(instrument: str, regime_state: RegimeState, entry_df: pd.DataFrame,
             cfg: AppConfig, strategy: Optional[BaseStrategy], *,
             in_session: bool, allowed_regimes, mtf_aligned: Optional[bool],
             is_mean_rev_only: bool, is_momentum_only: bool) -> Evaluation:
    """Build the per-instrument evaluation. `status` uses the real strategy's
    generate_signal verdict so it can never disagree with live trading; the
    reason/setup_distance/detail are display-only breakdowns."""
    regime = regime_state.regime

    # ── gates (mirror run_cycle order) ──
    if not in_session:
        return Evaluation(instrument, regime.value, False, None, "gated",
                          "out of session window", None, {})
    if is_mean_rev_only and regime in _TREND:
        return _gated(instrument, regime, "mean-reversion-only pair, regime trending")
    if is_momentum_only and regime == Regime.RANGING:
        return _gated(instrument, regime, "momentum-only pair, regime ranging")
    if allowed_regimes is not None and regime not in allowed_regimes:
        return _gated(instrument, regime, f"session-regime gate: {regime.value} not allowed this hour")
    if regime in _TREND and mtf_aligned is False:
        return _gated(instrument, regime, "H4/D1 not aligned")

    # ── reached the strategy: real verdict drives status ──
    if strategy is None:
        return _gated(instrument, regime, "no strategy for regime")
    would_signal = strategy.generate_signal(entry_df, regime_state) is not None

    if regime in (Regime.RANGING, Regime.CHOPPY):
        return _mr_eval(instrument, regime, entry_df, cfg.strategy.mean_reversion, would_signal)
    return _mom_eval(instrument, regime, entry_df, cfg.strategy.momentum, would_signal)


def _mr_eval(inst, regime, df, c, would_signal) -> Evaluation:
    rname, strat = regime.value, "mean_reversion"
    rsi = ta.rsi(df["close"], length=c.rsi_period)
    bb = ta.bbands(df["close"], length=20, std=c.bb_std)
    if rsi is None or bb is None or bool(rsi.isna().iloc[-1]):
        return Evaluation(inst, rname, True, strat, "no_setup", "insufficient indicator data", 0.0, {})
    bbl = next((x for x in bb.columns if x.startswith("BBL")), None)
    bbu = next((x for x in bb.columns if x.startswith("BBU")), None)
    if not bbl or not bbu:
        return Evaluation(inst, rname, True, strat, "no_setup", "bollinger columns missing", 0.0, {})

    close = float(df["close"].iloc[-1]); lower = float(bb[bbl].iloc[-1]); upper = float(bb[bbu].iloc[-1])
    rsi_now = float(rsi.iloc[-1])
    pct_b = (close - lower) / (upper - lower) if upper > lower else 0.5
    lower_touch, upper_touch = close <= lower, close >= upper
    distance = max(0.0, 1.0 - 2.0 * min(pct_b, 1.0 - pct_b))
    detail = {"pct_b": round(pct_b, 3), "rsi": round(rsi_now, 1),
              "lower_touch": lower_touch, "upper_touch": upper_touch,
              "rsi_oversold": c.rsi_oversold, "rsi_overbought": c.rsi_overbought}

    if would_signal:
        reason = "at band with RSI extreme — setup ready"
    elif not (lower_touch or upper_touch):
        reason = "price mid-band, not touching either band"
    elif lower_touch:
        reason = f"at lower band but RSI {rsi_now:.0f} not < {c.rsi_oversold:.0f}" \
                 if rsi_now >= c.rsi_oversold else "lower band touch — confirmation filters not met"
    else:
        reason = f"at upper band but RSI {rsi_now:.0f} not > {c.rsi_overbought:.0f}" \
                 if rsi_now <= c.rsi_overbought else "upper band touch — confirmation filters not met"

    return Evaluation(inst, rname, True, strat, "signal" if would_signal else "no_setup",
                      reason, round(distance, 3), detail)


def _mom_eval(inst, regime, df, c, would_signal) -> Evaluation:
    rname, strat = regime.value, "momentum"
    fast = ta.ema(df["close"], length=c.fast_ema)
    slow = ta.ema(df["close"], length=c.slow_ema)
    atr = compute_atr(df, period=14)
    rsi = ta.rsi(df["close"], length=c.rsi_period)
    if any(s is None or bool(s.isna().iloc[-1]) for s in (fast, slow, atr, rsi)):
        return Evaluation(inst, rname, True, strat, "no_setup", "insufficient indicator data", 0.0, {})

    close = float(df["close"].iloc[-1]); prev = float(df["close"].iloc[-2]); prev2 = float(df["close"].iloc[-3])
    fast_now = float(fast.iloc[-1]); slow_now = float(slow.iloc[-1]); atr_now = float(atr.iloc[-1]); rsi_now = float(rsi.iloc[-1])
    slow_10 = float(slow.iloc[-10]) if len(slow) > 10 else slow_now
    slope_atr = (slow_now - slow_10) / atr_now if atr_now > 0 else 0.0
    try:
        adx_rising = _adx_is_rising(compute_adx(df, 14)["adx"])
    except ValueError:
        adx_rising = True
    down = regime == Regime.TRENDING_DOWN
    ema_aligned = fast_now < slow_now if down else fast_now > slow_now
    slope_ok = slope_atr < -_SLOPE_MIN_ATR if down else slope_atr > _SLOPE_MIN_ATR
    rsi_ok = rsi_now < c.rsi_midline if down else rsi_now > c.rsi_midline
    if down:
        ema_touch = float(df["high"].iloc[-2]) >= fast_now * 0.999
        bounce = (close < prev) and (prev < prev2)
    else:
        ema_touch = float(df["low"].iloc[-2]) <= fast_now * 1.001
        bounce = (close > prev) and (prev > prev2)

    checks = [
        ("adx_rising", adx_rising, "ADX not rising"),
        ("ema_aligned", ema_aligned, "fast/slow EMA not aligned"),
        ("slope_ok", slope_ok, "slow-EMA slope too shallow"),
        ("rsi_ok", rsi_ok, "RSI not past midline"),
        ("ema_touch", ema_touch, "no pullback to fast EMA"),
        ("bounce", bounce, "no two-bar bounce"),
    ]
    passed = sum(1 for _, ok, _ in checks)
    detail = {k: ok for k, ok, _ in checks}
    detail.update({"slope_atr": round(slope_atr, 3), "rsi": round(rsi_now, 1)})

    if would_signal:
        reason = "trend + pullback aligned — setup ready"
    else:
        reason = next((msg for _, ok, msg in checks if not ok), "entry filters not met")

    return Evaluation(inst, rname, True, strat, "signal" if would_signal else "no_setup",
                      reason, round(passed / len(checks), 3), detail)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd bot && ./.venv/Scripts/python.exe -m pytest tests/test_evaluator.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add bot/src/insight/__init__.py bot/src/insight/evaluator.py bot/tests/test_evaluator.py
git commit -m "feat(insight): per-instrument evaluator (status from real strategy verdict)"
```

---

## Task 3: Persist evaluations via SupabaseLogger

**Files:**
- Modify: `bot/src/db/supabase_client.py`
- Test: `bot/tests/test_supabase_client.py`

- [ ] **Step 1: Write failing test**

Append to `bot/tests/test_supabase_client.py`:
```python
def test_upsert_signal_evaluation_upserts_by_instrument():
    from src.insight.evaluator import Evaluation
    client, chain = _fake_client()
    ev = Evaluation("EURUSDm", "RANGING", True, "mean_reversion",
                    "no_setup", "price mid-band", 0.34, {"pct_b": 0.34})
    SupabaseLogger(client).upsert_signal_evaluation(ev)
    client.table.assert_called_with("signal_evaluations")
    payload = chain.upsert.call_args[0][0]
    assert payload["instrument"] == "EURUSDm"
    assert payload["status"] == "no_setup"
    assert payload["detail"] == {"pct_b": 0.34}
    assert chain.upsert.call_args.kwargs["on_conflict"] == "instrument"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bot && ./.venv/Scripts/python.exe -m pytest tests/test_supabase_client.py::test_upsert_signal_evaluation_upserts_by_instrument -q`
Expected: FAIL — `AttributeError: 'SupabaseLogger' object has no attribute 'upsert_signal_evaluation'`.

- [ ] **Step 3: Implement the method**

In `bot/src/db/supabase_client.py`, add the import at the top (after the existing `from src.models...` imports):
```python
from src.insight.evaluator import Evaluation
```
Add this method to `SupabaseLogger` (e.g. after `record_trade`):
```python
    def upsert_signal_evaluation(self, ev: Evaluation) -> None:
        self._safe_upsert("signal_evaluations", {
            "instrument": ev.instrument,
            "regime": ev.regime,
            "in_session": ev.in_session,
            "strategy": ev.strategy,
            "status": ev.status,
            "reason": ev.reason,
            "setup_distance": ev.setup_distance,
            "detail": ev.detail,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="instrument")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd bot && ./.venv/Scripts/python.exe -m pytest tests/test_supabase_client.py -q`
Expected: PASS (all tests in file).

- [ ] **Step 5: Commit**

```bash
git add bot/src/db/supabase_client.py bot/tests/test_supabase_client.py
git commit -m "feat(db): SupabaseLogger.upsert_signal_evaluation"
```

---

## Task 4: Wire the evaluation pass into run_cycle

**Files:**
- Modify: `bot/src/bot.py`
- Test: `bot/tests/test_bot_orchestrator.py`

Context: `run_cycle` already builds `regime_states` (a list of `RegimeState`) for all instruments around line 114-122, computes `selected`, and runs the signal loop. `self._strategies` maps regime → strategy. `_MEAN_REV_ONLY` / `_MOMENTUM_ONLY` are module-level frozensets. `_in_session`, `_session_allowed_regimes`, `_h4_aligned`, `_d1_aligned` are methods. The entry timeframe is `self._cfg.timeframes.entry`; `self._fetcher.fetch_ohlcv` is cached within a cycle.

- [ ] **Step 1: Write failing test**

Append to `bot/tests/test_bot_orchestrator.py`:
```python
@pytest.mark.asyncio
async def test_run_cycle_upserts_one_evaluation_per_instrument():
    mcp = FakeMCPClient(responses={
        "get_rates": _rates(), "get_positions": [],
        "account_info": {"balance": 500},
        "get_symbol_info": {"spread": 1.0, "avg_spread": 1.0},
    })
    supabase = MagicMock()
    cfg = AppConfig(account={"starting_balance": 500},
                    instruments=["EURUSD", "GBPUSD"])
    await TradingBot(cfg, mcp, supabase).run_cycle()
    evaluated = {c.args[0].instrument
                 for c in supabase.upsert_signal_evaluation.call_args_list}
    assert evaluated == {"EURUSD", "GBPUSD"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bot && ./.venv/Scripts/python.exe -m pytest tests/test_bot_orchestrator.py::test_run_cycle_upserts_one_evaluation_per_instrument -q`
Expected: FAIL — `assert set() == {'EURUSD', 'GBPUSD'}` (method never called).

- [ ] **Step 3: Add the import**

At the top of `bot/src/bot.py`, with the other `from src...` imports (after `_crumb("SRC_IMPORTS")` block is fine), add:
```python
from src.insight.evaluator import evaluate
```

- [ ] **Step 4: Add the evaluation pass**

In `run_cycle`, immediately AFTER the regime-classification loop that fills `regime_states` (the `for instrument in self._cfg.instruments:` loop ending with `self._db.snapshot_regime(state)`), insert:
```python
        # Per-instrument evaluation for the Insight view (why did/didn't we signal)
        await self._write_evaluations(regime_states)
```

Then add this method to the `TradingBot` class (place it right before `_detect_closed_trades`):
```python
    async def _write_evaluations(self, regime_states: list[RegimeState]) -> None:
        for state in regime_states:
            inst = state.instrument
            try:
                in_session = self._in_session(inst)
                allowed = self._session_allowed_regimes(inst)
                mtf = None
                if state.regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
                    direction = "BUY" if state.regime == Regime.TRENDING_UP else "SELL"
                    mtf = (await self._h4_aligned(inst, direction)
                           and await self._d1_aligned(inst, direction))
                edf = await self._fetcher.fetch_ohlcv(
                    inst, self._cfg.timeframes.entry, bars=200)
                ev = evaluate(
                    inst, state, edf, self._cfg,
                    self._strategies.get(state.regime),
                    in_session=in_session, allowed_regimes=allowed, mtf_aligned=mtf,
                    is_mean_rev_only=inst in _MEAN_REV_ONLY,
                    is_momentum_only=inst in _MOMENTUM_ONLY,
                )
                self._db.upsert_signal_evaluation(ev)
            except Exception:
                log.exception("Evaluation write failed for %s", inst)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd bot && ./.venv/Scripts/python.exe -m pytest tests/test_bot_orchestrator.py -q`
Expected: PASS (all tests in file).

- [ ] **Step 6: Run the full bot suite for regressions**

Run: `cd bot && ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 7: Commit**

```bash
git add bot/src/bot.py bot/tests/test_bot_orchestrator.py
git commit -m "feat(bot): write per-instrument evaluations each cycle"
```

---

## Task 5: Dashboard type + Nav link

**Files:**
- Modify: `dashboard/lib/types.ts`
- Modify: `dashboard/components/Nav.tsx`

- [ ] **Step 1: Add the `SignalEvaluation` interface**

Append to `dashboard/lib/types.ts`:
```typescript
export interface SignalEvaluation {
  instrument: string
  regime: string | null
  in_session: boolean | null
  strategy: string | null
  status: "signal" | "gated" | "no_setup"
  reason: string | null
  setup_distance: number | null
  detail: Record<string, unknown> | null
  updated_at: string
}
```

- [ ] **Step 2: Add the Insight nav link**

In `dashboard/components/Nav.tsx`, change the `links` array to include Insight after Performance:
```typescript
const links = [
  { href: "/",            label: "OVERVIEW",    key: "F1" },
  { href: "/positions",   label: "POSITIONS",   key: "F2" },
  { href: "/signals",     label: "SIGNALS",     key: "F3" },
  { href: "/trades",      label: "TRADES",      key: "F4" },
  { href: "/performance", label: "PERFORMANCE", key: "F5" },
  { href: "/insight",     label: "INSIGHT",     key: "F6" },
]
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/lib/types.ts dashboard/components/Nav.tsx
git commit -m "feat(dashboard): SignalEvaluation type + Insight nav link"
```

---

## Task 6: The Insight page

**Files:**
- Create: `dashboard/app/insight/page.tsx`

Context: client pages use `import { supabase } from "@/lib/supabase"`, subscribe via `supabase.channel(...).on("postgres_changes", ...)`, and style with CSS vars (`var(--panel)`, `var(--border)`, `var(--green)`, `var(--red)`, `var(--yellow)`, `var(--muted)`, `var(--dim)`, `var(--accent)`). `timeAgo` is exported from `@/lib/fmt`.

- [ ] **Step 1: Create the page**

Create `dashboard/app/insight/page.tsx`:
```tsx
"use client"
import { useEffect, useState, useCallback } from "react"
import { supabase } from "@/lib/supabase"
import type { SignalEvaluation } from "@/lib/types"
import { timeAgo } from "@/lib/fmt"

const STATUS = {
  signal:   { color: "var(--green)",  label: "SETUP READY" },
  no_setup: { color: "var(--yellow)", label: "NO SETUP" },
  gated:    { color: "var(--muted)",  label: "GATED" },
} as const

function Bar({ value }: { value: number | null }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value))
  const color = pct > 0.66 ? "var(--green)" : pct > 0.33 ? "var(--yellow)" : "var(--dim)"
  return (
    <div style={{ width: 90, height: 4, background: "var(--border-hi)" }}>
      <div style={{ width: `${pct * 100}%`, height: "100%", background: color, transition: "width 0.4s" }} />
    </div>
  )
}

function Row({ e }: { e: SignalEvaluation }) {
  const [open, setOpen] = useState(false)
  const s = STATUS[e.status] ?? STATUS.gated
  const stale = e.updated_at ? Date.now() - new Date(e.updated_at).getTime() > 5 * 60 * 1000 : false
  return (
    <div style={{ borderBottom: "1px solid var(--border)", opacity: stale ? 0.5 : 1 }}>
      <div onClick={() => e.detail && setOpen(o => !o)}
        style={{ display: "grid", gridTemplateColumns: "120px 110px 110px 90px 1fr", gap: "1rem",
          alignItems: "center", padding: "0.6rem 0.85rem", cursor: e.detail ? "pointer" : "default" }}>
        <span style={{ fontWeight: 700, fontSize: "0.8rem" }}>{e.instrument}</span>
        <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>{e.regime ?? "—"}</span>
        <span style={{ fontSize: "0.62rem", fontWeight: 700, letterSpacing: "0.06em", color: s.color }}>{s.label}</span>
        <Bar value={e.setup_distance} />
        <span style={{ fontSize: "0.65rem", color: "var(--dim)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.reason ?? ""}</span>
      </div>
      {open && e.detail && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem 1.25rem",
          padding: "0.4rem 0.85rem 0.7rem", fontSize: "0.6rem", color: "var(--muted)" }}>
          {Object.entries(e.detail).map(([k, v]) => (
            <span key={k}>
              {k}: <span style={{ color: v === true ? "var(--green)" : v === false ? "var(--red)" : "var(--sub)" }}>
                {String(v)}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Insight() {
  const [rows, setRows] = useState<SignalEvaluation[]>([])

  const load = useCallback(() =>
    supabase.from("signal_evaluations").select("*").order("instrument")
      .then(({ data }) => data && setRows(data as SignalEvaluation[])), [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30_000)
    const ch = supabase.channel("insight-rt")
      .on("postgres_changes", { event: "*", schema: "public", table: "signal_evaluations" }, load)
      .subscribe()
    return () => { supabase.removeChannel(ch); clearInterval(timer) }
  }, [load])

  const latest = rows.reduce<string | null>((a, r) => !a || r.updated_at > a ? r.updated_at : a, null)

  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "1rem", marginBottom: "0.75rem" }}>
        <h1 style={{ fontSize: "0.85rem", letterSpacing: "0.1em", color: "var(--text)" }}>WHY NO SIGNAL</h1>
        {latest && <span style={{ fontSize: "0.6rem", color: "var(--dim)" }}>updated {timeAgo(latest)} ago</span>}
      </div>
      <div style={{ background: "var(--panel)", border: "1px solid var(--border)" }}>
        {rows.map(e => <Row key={e.instrument} e={e} />)}
        {rows.length === 0 && (
          <div style={{ padding: "2rem", textAlign: "center", color: "var(--muted)", fontSize: "0.72rem" }}>
            — no evaluations yet —
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify the build typechecks**

Run: `cd dashboard && npm run build`
Expected: build completes with no type errors; route `/insight` listed in the output.

- [ ] **Step 3: Commit**

```bash
git add dashboard/app/insight/page.tsx
git commit -m "feat(dashboard): Insight page (why no signal)"
```

---

## Task 7: End-to-end verification

**Files:** none (manual verification)

- [ ] **Step 1: Restart the bot so it writes evaluations**

Stop any running `main.py` python process, then:
Run: `cd bot && ./.venv/Scripts/python.exe main.py > bot.log 2> bot.err` (background)
Wait for `MCP connected`, then wait ~70s for one full cycle.

- [ ] **Step 2: Confirm rows are written**

Via Supabase MCP `execute_sql`:
```sql
SELECT instrument, regime, status, round(setup_distance,2) AS dist, reason
FROM signal_evaluations ORDER BY instrument;
```
Expected: one row per configured instrument with a sensible `status`/`reason` matching the live market (cross-check against `diag_strategy_conditions.py` output).

- [ ] **Step 3: Confirm the page renders**

Run: `cd dashboard && npm run dev`, open `http://localhost:3000/insight`.
Expected: a row per instrument with regime, status label, distance bar, and reason; clicking a row expands the `detail` checklist. (Requires `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` in `dashboard/.env.local`.)

- [ ] **Step 4: Final commit (if any verification tweaks were needed)**

```bash
git add -A
git commit -m "chore: verify insight view end-to-end"
```

---

## Self-Review Notes

- **Spec coverage:** table (T1), evaluator+drift safety (T2 — status uses real `generate_signal`, so it cannot drift; tests assert fidelity), persistence (T3), per-cycle write for all instruments (T4), type+nav (T5), page with status/distance/reason/expandable detail (T6), verification incl. cross-check vs the diagnostic (T7). London Breakout excluded per spec non-goal (only regime-routed strategies evaluated).
- **Status fidelity:** `evaluate()` derives `status` from the routed strategy's real `generate_signal()` verdict — a stronger guarantee than the spec's "replicate + drift-guard" wording. The breakdown (`reason`/`detail`/`setup_distance`) is display-only.
- **Realtime:** migration adds the table to `supabase_realtime` (T1 Step 2); page subscribes to `*` (T6).
```
