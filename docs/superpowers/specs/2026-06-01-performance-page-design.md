# Performance Page Redesign — Design

- **Date:** 2026-06-01
- **Status:** Approved
- **Owner:** jrwal

## Problem

`performance_daily` has 0 rows — it is populated by an end-of-day bot job that has not run yet. The current `/performance` page reads exclusively from that table and therefore renders completely blank. There are 10 real closed trades in the `trades` table spanning 2026-05-29 to 2026-06-01 that contain all the data needed.

## Goal

A useful performance page that works immediately and stays accurate as new trades arrive, computed entirely from the `trades` table.

## Non-goals (YAGNI)

- No time-period filter (only 10 trades; filtering would leave nothing meaningful).
- No changes to `performance_daily` or the bot's daily summary job.
- No new Supabase tables, columns, or migrations.
- No server-side aggregation — all computation client-side from raw trade rows.

## Data source

Single query on mount + realtime INSERT subscription:

```typescript
supabase
  .from("trades")
  .select("*")
  .not("closed_at", "is", null)
  .order("closed_at", { ascending: true })
```

All closed trades in chronological order. The realtime channel fires `load()` on every INSERT so new trades appear immediately without a page refresh.

## Computed metrics (all client-side)

From the sorted trade array:

| Metric | Formula |
|---|---|
| Total P&L | `sum(profit)` |
| Win rate | `count(profit > 0) / count(*)` |
| Total trades | `count(*)` |
| Profit factor | `sum(profit where profit > 0) / abs(sum(profit where profit < 0))`; show "—" if no losses |
| Avg win | `mean(profit where profit > 0)` |
| Avg loss | `mean(profit where profit < 0)` |
| Equity series | running `cumsum(profit)` ordered by `closed_at` — one point per trade |
| Per-trade P&L | raw `profit` per row, same order |

**Strategy breakdown** — group trades by `strategy` field:
- Per group: trades count, win rate, total P&L, avg win, avg loss, profit factor
- Rows sorted by total P&L descending
- `strategy = "unknown"` shown as a normal row (honest about pre-attribution trades; as new attributed trades arrive they appear in separate rows)

## Layout

Two vertical sections, full-width page:

### Section 1 — Equity & overview stats

1. **Stat boxes row** (6 boxes, responsive grid): Total P&L · Win Rate · Trades · Profit Factor · Avg Win · Avg Loss
2. **Equity curve** (full-width area chart, recharts `AreaChart`): cumulative running P&L by trade, zero-line reference line. X-axis = `closed_at` formatted as `MM-DD HH:mm`, not calendar days. This ensures it plots correctly even with only a few trades across a few days.
3. **Per-trade P&L bars** (full-width `BarChart`): one bar per trade ordered by close time, green for profit > 0, red for loss. Zero reference line.

### Section 2 — Strategy breakdown

Table with columns: **Strategy · Trades · Win Rate · Total P&L · Avg Win · Avg Loss · Profit Factor**

Sorted by total P&L descending. No special styling for "unknown" rows.

## Styling

Follows existing dashboard patterns:
- CSS vars: `var(--panel)`, `var(--border)`, `var(--green)`, `var(--red)`, `var(--accent)`, `var(--muted)`, `var(--dim)`, `var(--teal)`
- Recharts `tooltipStyle` pattern from the existing file
- `StatBox` component reused from existing implementation
- `fmtPnl` from `@/lib/fmt`
- Empty state when no trades: "— no closed trades yet —"

## Files changed

| File | Change |
|---|---|
| `dashboard/app/performance/page.tsx` | Full rewrite — remove `performance_daily` dependency, add equity curve + P&L bars + strategy table computed from trades |

No other files need to change. `PerformanceDaily` type in `lib/types.ts` can stay (unused but harmless).

## Testing

- `npm run build` passes with no type errors
- Screenshot the page with the 10 existing trades to verify all three sections render correctly
- Verify an empty-trades state renders the empty message rather than crashing
