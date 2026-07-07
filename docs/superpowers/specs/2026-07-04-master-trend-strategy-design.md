# Master Trend Strategy — Design

**Date:** 2026-07-04
**Status:** Approved (pending spec review)

## Goal

Port the TradingView "Master Trend Strategy v1.1" Pine script into the Algobot
Python bot, restricted to the **M15 timeframe** on **USTECm** and **US30m** only.
Faithful reproduction of the entry logic (Master Trend signals + Rejection
orders), fixed percentage TP/SL, and R-based breakeven/trailing exit management,
using the settings from the user's two configuration screenshots.

Only the trading logic is ported. The Pine script's chart visuals (trend boxes,
labels, live P&L, stats/last-signal tables) are out of scope — the bot's
dashboard already handles visualization.

## Scope

- **MT Signals + Rejections** — both order types are ported.
- **Instruments:** USTECm, US30m (M15 entry timeframe, already the bot default).
- **Coexistence:** runs as an independent parallel pass *alongside* the existing
  momentum / mean-reversion routing for these instruments. The RiskManager's
  concurrent-position and correlation limits remain the only cross-check.
- **Disabled Pine features omitted (YAGNI):** EMA750 proximity filter (off in
  both screenshots), pyramiding (off), time filter (off). Long and short both
  enabled.

## Settings (from screenshots)

| Setting | MT Signals | Rejections |
|---|---|---|
| Take Profit % | 0.5 | 0.3 |
| Stop Loss % | 0.1 | 0.1 |
| Breakeven at RR | 2.0 | 2.0 |
| Trailing start at RR | 3.0 | 3.0 |
| Trailing step (pips) | 50 | 50 |
| EMA750 proximity filter | off | off |
| Pyramiding | off | off |

Global: Long + Short enabled, Time Filter off, MT line length = 25 bars,
UTC offset = 2 (used only by the Pine time filter, which is off — so it has no
effect on the port).

## Configuration

New `MasterTrendStrategyConfig` in `src/config/schema.py`, added to
`StrategyConfig`, and a `master_trend:` block in `config/settings.yaml`:

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
  time_filter_enabled: false
```

## Architecture

### Component: `MasterTrendStrategy` (`src/strategies/master_trend.py`)

Implements `BaseStrategy.generate_signal(df, regime) -> Optional[Signal]`.
Stateless across calls — rebuilds trend-line state deterministically from the
supplied dataframe each call (see Rejection logic).

**Indicators** (computed with `pandas_ta`, on the M15 dataframe):

- `rsi(14)`, `ema(4)`, `ema(5)`, `ema(21)`, `sma(50)`, `ema(55)`, `ema(89)`,
  `ema(750)`.
- **Stochastic %K:** `stoK = SMA( 100·(close − LL₁₀)/(HH₁₀ − LL₁₀), 3 )`,
  computed manually to exactly match Pine's `ta.sma(ta.stoch(close,high,low,10),3)`.
- **Session VWAP:** anchored to the UTC calendar day, `hl2`-weighted, resetting
  each day — faithful to Pine's `ta.vwap(hl2)`.
- EMA89 breakout: `close` crossing `ema89` (up = crossover, down = crossunder).
- Bullish / bearish engulfing candle detection.

**MT Bull signal** (evaluated on the last closed bar; all conditions required):

```
ema4 crosses above ema5
AND rsi > 50
AND close > ema21 AND close > sma50 AND close > ema55
    AND close > ema89 AND close > ema750
AND ( stoK > 52 OR ema89_bull_breakout OR vwap_cross_up
      OR (bull_engulf AND close > ema750) )
```

**MT Bear signal** is the exact mirror (`ema4` crosses below `ema5`, `rsi < 50`,
`close <` all EMAs, `stoK < 48 OR ema89_bear_breakout OR vwap_cross_down OR
(bear_engulf AND close < ema750)`).

Long signals are suppressed when `enable_long` is false; short likewise.

**TP/SL for an MT signal** (entry = last close):
- BUY: `TP = close·(1 + tp_pct_mt/100)`, `SL = close·(1 − sl_pct_mt/100)`
- SELL: `TP = close·(1 − tp_pct_mt/100)`, `SL = close·(1 + sl_pct_mt/100)`

### Rejection logic (stateful, rebuilt deterministically)

On each call the strategy scans the dataframe window to reconstruct the set of
**active Master Trend lines**: for every bar in the window where an MT signal
(bull or bear) fired, a horizontal line exists at that bar's `open` price, valid
for the following `line_extension_bars` (25) bars.

The **current (last) bar** is then tested against every still-valid line:

- **Bull rejection:** `low ≤ line_price` AND `close > line_price` AND
  `close > ema750`.
- **Bear rejection:** `high ≥ line_price` AND `close < line_price` AND
  `close < ema750`.

The first matching line emits a Rejection `Signal` using the `_rej` percentages.
Rebuilding from the dataframe each cycle (rather than mutating instance state)
keeps the strategy correct across bot restarts and missed cycles.

MT and Rejection signals are independent; if both fire on the same bar, MT is
evaluated first (matching the Pine ordering). The bot's existing 5-minute
per-(instrument, direction) dedup guard prevents the same bar re-firing across
cycles.

### History requirement

`ema(750)` needs ≥ 750 bars. The Master Trend parallel pass fetches **~900 M15
bars** for these instruments (existing passes use 200). The strategy returns
`None` until at least 750 valid bars exist, rather than emitting a distorted
early-EMA signal.

### Exit management (`_trail_sl` `master_trend` branch in `bot.py`)

Entry places broker-side fixed TP/SL (the percentages above). A new branch keyed
on `pos.strategy == "master_trend"` replicates Pine's management, where
`R = |entry − original_SL|`:

- **Breakeven:** when price reaches `entry ± be_ratio·R` (2R), move SL to
  `entry`.
- **Trailing:** when price reaches `entry ± trail_start_rr·R` (3R), begin
  trailing; SL follows `high_water − trail_step_pips·pipSize` (BUY) /
  `low_water + trail_step_pips·pipSize` (SELL), only ever tightening.

**Original-R persistence:** once SL moves to breakeven the original SL distance
is lost, so the bot caches `{ticket: r_distance}` (and `{ticket: high_water}`)
at fill time. In-memory, session-scoped, no DB schema change.

**pipSize for indices:** read from the symbol's `mintick` via `get_symbol_info`
(Pine uses `syminfo.mintick·1` for non-forex), with a configurable fallback if
unavailable — so "50 pips" means exactly what it does on the TradingView chart.

### Bot integration (`src/bot.py`)

A new parallel pass, structured like the London Breakout pass:

1. For each configured pair in session, fetch ~900 M15 bars.
2. Call `MasterTrendStrategy.generate_signal`.
3. Apply the existing pipeline: dedup guard → RiskManager evaluation → optional
   AI validation → `place_order` → `log_signal`.
4. On fill, cache the ticket's R-distance for `_trail_sl`.

## Testing

`bot/tests/test_master_trend_strategy.py`, following the existing strategy-test
style:

- Synthetic M15 frame producing a clean MT bull signal → asserts BUY, TP/SL math.
- Same for MT bear → SELL.
- Each confirmation branch (stoch / ema89 breakout / vwap cross / engulf) in
  isolation.
- Rejection: a bar wicking a prior MT line and recovering → rejection signal; a
  bar closing through the line → no signal.
- Guards: < 750 bars → `None`; `enable_long=false` suppresses BUY;
  `enable_short=false` suppresses SELL.
- `_trail_sl` `master_trend` branch: breakeven at 2R, trailing at 3R/50-pip,
  monotonic tightening (SL never loosens).

## Files

- **New:** `src/strategies/master_trend.py`, `tests/test_master_trend_strategy.py`
- **Edit:** `src/config/schema.py` (add `MasterTrendStrategyConfig`),
  `config/settings.yaml` (add `master_trend` block), `src/bot.py` (parallel pass,
  `_trail_sl` branch, per-ticket R-distance/high-water cache).

## Out of scope

- Chart visuals (boxes, labels, live P&L, stats & last-signal tables).
- EMA750 proximity filter, pyramiding, time filter (all disabled in settings).
- Changes to existing momentum / mean-reversion behavior on these instruments.
