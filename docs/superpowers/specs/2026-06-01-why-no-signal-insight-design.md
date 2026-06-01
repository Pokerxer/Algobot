# Why-No-Signal Insight View — Design

- **Date:** 2026-06-01
- **Status:** Approved (design); pending spec review
- **Owner:** jrwal

## Goal & context

The bot frequently produces zero signals (see the 2026-06-01 investigation: strategies
return `None` because the market offers no setup, and several instruments are blocked by
session/regime gates). Today that reasoning is invisible — it only exists transiently
inside `run_cycle` and in throwaway diagnostic scripts. This feature surfaces it as a live
dashboard page: for every instrument, *why isn't the bot trading it right now, and how close
is it to a setup?*

## Decisions (from brainstorming)

1. **Feature:** a "Why no signal" insight view — the diagnostic-as-a-live-panel.
2. **Data source:** the bot persists a per-instrument evaluation each cycle to a new table
   (the dashboard cannot recompute indicators itself).
3. **Placement:** a new dedicated **Insight** page (not crammed into the dense Overview).
4. **Evaluator approach:** **B — a standalone evaluator** module. It does *not* modify the
   live trading strategies. To neutralise the risk of the evaluator drifting from the real
   strategy logic, a **drift-guard test** asserts the evaluator's "would signal" verdict
   matches the real `generate_signal()` output across fixtures.

## Non-goals (YAGNI)

- No historical time-series of evaluations — the table holds only the latest state per
  instrument (one upserted row each). Charting "time spent in each regime" is out of scope.
- No changes to trading behaviour, strategy thresholds, or the session gates.
- No alerting/notifications.
- **London Breakout** parallel pass is excluded from v1 — each instrument's row reflects its
  primary regime-routed strategy (momentum / mean-reversion). LB is a niche pass (3 pairs,
  07–10 UTC) and folding it in would need a second per-instrument verdict; deferred.
- The view reflects *signal generation*, not execution — `status='signal'` means the strategy
  would emit a signal (a row in `signals`), independent of whether the risk manager would then
  approve/size it.

## 1. Data model — migration `004_signal_evaluations.sql`

One upserted row per instrument (current state), keyed by `instrument`:

```sql
CREATE TABLE public.signal_evaluations (
  instrument     text PRIMARY KEY,
  regime         text,
  in_session     boolean,
  strategy       text,            -- 'mean_reversion' | 'momentum' | null (gated)
  status         text NOT NULL,   -- 'signal' | 'gated' | 'no_setup'
  reason         text,            -- short human reason (first-fail or gate)
  setup_distance numeric,         -- 0..1 proximity to a setup; null when gated
  detail         jsonb,           -- per-condition breakdown for drill-down
  updated_at     timestamptz DEFAULT now()
);

ALTER TABLE public.signal_evaluations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_read" ON public.signal_evaluations;
CREATE POLICY "anon_read" ON public.signal_evaluations FOR SELECT TO anon USING (true);
ALTER PUBLICATION supabase_realtime ADD TABLE signal_evaluations;
```

**`status` semantics**
- `signal` — passes every gate and the routed strategy would emit a signal this cycle.
- `gated` — blocked *before* reaching the strategy (out of session, session-regime gate,
  instrument routing, or H4/D1 misalignment). `strategy` and `setup_distance` are null.
- `no_setup` — reached the strategy, but `generate_signal` returns `None` (no entry trigger).

**`setup_distance` (0..1)**
- Mean-reversion: band proximity — `max(0, 1 - 2*min(pct_b, 1-pct_b))`. At a band edge
  (`%B`=0 or 1) → 1.0; mid-band (`%B`=0.5) → 0.0.
- Momentum: fraction of the ordered checks passed before the first failure (e.g. 5/6 → 0.83).
- `gated` → null.

**`detail` (jsonb)** — the per-condition breakdown powering the expandable row:
- MR: `{ pct_b, rsi, lower_touch, upper_touch, double_touch, divergence }`
- Momentum: `{ adx_rising, ema_aligned, slope_atr, slope_ok, rsi, rsi_ok, ema_touch, bounce }`

## 2. Bot

### `bot/src/insight/evaluator.py` (new, pure unit)

```python
@dataclass
class Evaluation:
    instrument: str
    regime: str
    in_session: bool
    strategy: str | None
    status: str            # 'signal' | 'gated' | 'no_setup'
    reason: str
    setup_distance: float | None
    detail: dict

def evaluate(instrument, regime_state, entry_df, cfg, *,
             in_session: bool,
             allowed_regimes: frozenset | None,
             mtf_aligned: bool | None) -> Evaluation: ...
```

The bot pre-computes the three gate inputs it already knows how to derive (`in_session` via
`TradingBot._in_session`, `allowed_regimes` via `_session_allowed_regimes`, and for trending
regimes `mtf_aligned` via `_h4_aligned`/`_d1_aligned`). The evaluator is otherwise a pure
function over `entry_df` + `cfg`, keeping it independently testable.

**Gate order (mirrors `run_cycle` lines ~146–195), short-circuiting to `status='gated'`:**
1. `not in_session` → reason "out of session window".
2. `instrument in _MEAN_REV_ONLY and regime in TREND` → "mean-reversion-only pair, regime trending".
3. `instrument in _MOMENTUM_ONLY and regime == RANGING` → "momentum-only pair, regime ranging".
4. `allowed_regimes is not None and regime not in allowed_regimes` → "session-regime gate: <regime> not allowed this hour".
5. trending and `mtf_aligned is False` → "H4/D1 not aligned".

**Reached strategy** → compute the condition breakdown (reusing the strategies' module-level
helpers `_adx_is_rising`, `_SLOPE_MIN_ATR`, `_rsi_diverges_bullish` to reduce drift), set
`status` to `signal`/`no_setup`, `reason` to the first failing condition, `setup_distance`
and `detail` per §1. The evaluator replicates the *full* strategy condition set (incl.
double-touch, divergence, volume) so `status=='signal'` is faithful — guarded by the test below.

`_MEAN_REV_ONLY` / `_MOMENTUM_ONLY` and `TREND` are imported from `src.bot`.

### `SupabaseLogger.upsert_signal_evaluation(ev: Evaluation)`

Upsert into `signal_evaluations` on `on_conflict=instrument`, following the existing
`upsert_position` pattern (with `_RESET_ERRORS` retry). `detail` is serialised as JSON.

### `run_cycle` wiring

After regime classification (it already builds `regime_states` for all instruments), add a
pass over the configured instruments: derive the gate inputs, fetch the entry-timeframe df
(cache hit for instruments already fetched in the signal loop), call `evaluate`, and
`upsert_signal_evaluation`. Wrapped so a failure logs and never breaks the trading cycle.

## 3. Dashboard

- **`lib/types.ts`** — add `SignalEvaluation` interface mirroring the table.
- **`components/Nav.tsx`** — add an **Insight** nav link.
- **`app/insight/page.tsx`** (new, `"use client"`) — reads `signal_evaluations`
  (`select * order by instrument`), subscribes to realtime `*` on the table plus a 30s poll
  (same pattern as Overview). Renders a board of instrument rows:
  - regime badge, routed strategy, status colour (`signal` green / `no_setup` amber / `gated` grey),
  - a `setup_distance` progress bar,
  - the short `reason`,
  - click-to-expand `detail` checklist (pass/fail per condition).
  Reuses `lib/fmt.ts` and the existing CSS-var visual language; rows older than 5 min render
  "stale" like `RegimeTile`.

## 4. Testing

- **Unit tests** for `evaluate()` over fixture dataframes: a mean-reversion `no_setup`
  (mid-band) case, a mean-reversion band-touch case, a momentum `no_setup` case, and a
  `gated` case (out of session).
- **Drift-guard test:** for a set of fixture df + regime pairs, assert
  `evaluate(...).status == 'signal'` **iff** the real `MeanReversionStrategy` /
  `MomentumStrategy.generate_signal(...)` returns non-`None`. This is the safety net for
  choosing the standalone-evaluator approach.
- **Dashboard:** `next build` / typecheck passes.

## File-by-file change list

| File | Change |
|---|---|
| `supabase/migrations/004_signal_evaluations.sql` | new table + RLS + realtime |
| `bot/src/insight/__init__.py`, `bot/src/insight/evaluator.py` | new evaluator unit |
| `bot/src/db/supabase_client.py` | `upsert_signal_evaluation()` |
| `bot/src/bot.py` | evaluation pass in `run_cycle` |
| `bot/tests/test_evaluator.py` | unit + drift-guard tests |
| `dashboard/lib/types.ts` | `SignalEvaluation` |
| `dashboard/components/Nav.tsx` | Insight link |
| `dashboard/app/insight/page.tsx` | new page |
