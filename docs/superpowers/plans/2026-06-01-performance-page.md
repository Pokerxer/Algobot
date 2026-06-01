# Performance Page Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `/performance` to compute all stats from the `trades` table so the page works immediately instead of showing blank (performance_daily has 0 rows).

**Architecture:** Single `dashboard/app/performance/page.tsx` rewrite. Pure helper functions compute equity series, stat totals, and per-strategy breakdown from sorted trade rows. Recharts renders equity curve (AreaChart) and per-trade P&L bars (BarChart). No new tables, migrations, or API changes.

**Tech Stack:** Next.js 16, React 19, TypeScript, Recharts 3, Supabase JS, Tailwind/CSS vars.

---

## File Structure

| File | Change |
|---|---|
| `dashboard/app/performance/page.tsx` | Full rewrite — remove performance_daily dependency, add three sections |

No other files change.

---

## Task 1: Pure helper functions + type definitions

These are the computational core. Write them first so they can be tested in isolation before the UI is built.

**Files:**
- Modify: `dashboard/app/performance/page.tsx` (write fresh file from scratch)

The `Trade` type is already in `dashboard/lib/types.ts`:
```typescript
interface Trade {
  id: number; ticket: number; instrument: string; direction: string | null;
  entry_price: number | null; exit_price: number | null; volume: number | null;
  profit: number | null; opened_at: string | null; closed_at: string | null;
  strategy: string | null; regime: string | null; ai_decision: string | null;
  duration_minutes: number | null;
}
```

- [ ] **Step 1: Write the page file skeleton with helpers only**

Create `dashboard/app/performance/page.tsx` with this exact content:

```tsx
"use client"
import { useEffect, useState, useCallback } from "react"
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip,
         ResponsiveContainer, ReferenceLine, Cell } from "recharts"
import { supabase } from "@/lib/supabase"
import type { Trade } from "@/lib/types"
import { fmtPnl } from "@/lib/fmt"

// ── pure helpers (exported for testing) ──────────────────────────────────────

export function calcStats(trades: Trade[]) {
  const closed = trades.filter(t => t.profit != null)
  if (closed.length === 0)
    return { total: 0, wins: 0, losses: 0, winRate: null, totalPnl: 0,
             avgWin: null, avgLoss: null, profitFactor: null }
  const profits = closed.map(t => t.profit as number)
  const wins    = profits.filter(p => p > 0)
  const losses  = profits.filter(p => p < 0)
  const sumWins = wins.reduce((a, b) => a + b, 0)
  const sumLoss = losses.reduce((a, b) => a + b, 0)
  return {
    total:        closed.length,
    wins:         wins.length,
    losses:       losses.length,
    winRate:      wins.length / closed.length,
    totalPnl:     profits.reduce((a, b) => a + b, 0),
    avgWin:       wins.length   > 0 ? sumWins / wins.length   : null,
    avgLoss:      losses.length > 0 ? sumLoss / losses.length : null,
    profitFactor: losses.length > 0 ? sumWins / Math.abs(sumLoss) : null,
  }
}

export function calcEquitySeries(trades: Trade[]) {
  // Returns [{label, cumPnl, pnl}] one entry per closed trade, chronological.
  // label is "MM-DD HH:mm" from closed_at.
  let running = 0
  return trades
    .filter(t => t.profit != null && t.closed_at)
    .map(t => {
      running += t.profit as number
      const d = new Date(t.closed_at as string)
      const label = `${String(d.getUTCMonth() + 1).padStart(2,"0")}-${String(d.getUTCDate()).padStart(2,"0")} ${String(d.getUTCHours()).padStart(2,"0")}:${String(d.getUTCMinutes()).padStart(2,"0")}`
      return { label, cumPnl: parseFloat(running.toFixed(2)), pnl: t.profit as number }
    })
}

export function calcStrategyBreakdown(trades: Trade[]) {
  // Returns array of per-strategy stats sorted by totalPnl desc.
  const groups: Record<string, Trade[]> = {}
  trades.filter(t => t.profit != null).forEach(t => {
    const key = t.strategy ?? "unknown"
    ;(groups[key] ??= []).push(t)
  })
  return Object.entries(groups).map(([strategy, ts]) => {
    const profits = ts.map(t => t.profit as number)
    const wins    = profits.filter(p => p > 0)
    const losses  = profits.filter(p => p < 0)
    const sumWins = wins.reduce((a, b) => a + b, 0)
    const sumLoss = losses.reduce((a, b) => a + b, 0)
    return {
      strategy,
      trades:       ts.length,
      winRate:      wins.length / ts.length,
      totalPnl:     profits.reduce((a, b) => a + b, 0),
      avgWin:       wins.length   > 0 ? sumWins / wins.length   : null,
      avgLoss:      losses.length > 0 ? sumLoss / losses.length : null,
      profitFactor: losses.length > 0 ? sumWins / Math.abs(sumLoss) : null,
    }
  }).sort((a, b) => b.totalPnl - a.totalPnl)
}

// ── placeholder page (will be replaced in Task 2) ────────────────────────────

export default function PerformancePage() {
  return <div style={{ color: "var(--muted)", padding: "2rem" }}>loading…</div>
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd "C:\Users\jrwal\OneDrive\Documents\Algobot\dashboard" && npm run build 2>&1 | tail -8`
Expected: build succeeds, `/performance` listed in routes, no type errors.

- [ ] **Step 3: Manually smoke-test the helpers in Node**

Run:
```
cd "C:\Users\jrwal\OneDrive\Documents\Algobot\dashboard" && node -e "
// Inline the helpers (no imports needed for a quick smoke test)
function calcStats(trades) {
  const closed = trades.filter(t => t.profit != null)
  if (!closed.length) return { totalPnl: 0, winRate: null }
  const profits = closed.map(t => t.profit)
  const wins = profits.filter(p => p > 0)
  const losses = profits.filter(p => p < 0)
  return { total: closed.length, wins: wins.length,
           winRate: wins.length / closed.length,
           totalPnl: profits.reduce((a,b)=>a+b,0),
           profitFactor: losses.length > 0
             ? wins.reduce((a,b)=>a+b,0) / Math.abs(losses.reduce((a,b)=>a+b,0))
             : null }
}
const t = [
  { profit: 10, closed_at: '2026-01-01', strategy: 'momentum' },
  { profit: -5, closed_at: '2026-01-02', strategy: 'momentum' },
  { profit: 20, closed_at: '2026-01-03', strategy: 'mean_reversion' },
]
const s = calcStats(t)
console.assert(s.total === 3, 'total')
console.assert(Math.abs(s.totalPnl - 25) < 0.001, 'totalPnl')
console.assert(Math.abs(s.winRate - 2/3) < 0.001, 'winRate')
console.assert(Math.abs(s.profitFactor - 30/5) < 0.001, 'profitFactor')
console.log('calcStats OK', JSON.stringify(s))
"
```
Expected: `calcStats OK` with correct JSON, no assertion errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/performance/page.tsx
git commit -m "feat(perf): helper functions for trades-based performance metrics"
```

---

## Task 2: Full page implementation + verification

**Files:**
- Modify: `dashboard/app/performance/page.tsx` (replace placeholder `PerformancePage`)

- [ ] **Step 1: Replace `PerformancePage` with the full implementation**

Replace everything from `// ── placeholder page` to the end of the file with:

```tsx
// ── shared chart style ────────────────────────────────────────────────────────

const tooltipStyle = {
  contentStyle: {
    background: "var(--panel)", border: "1px solid var(--border)",
    borderRadius: 0, fontSize: 11, fontFamily: "inherit",
  },
  labelStyle: { color: "var(--muted)" },
  itemStyle:  { color: "var(--text)" },
}

// ── stat box ─────────────────────────────────────────────────────────────────

function StatBox({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--border)", padding: "0.85rem 1rem" }}>
      <div style={{ fontSize: "0.58rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.3rem" }}>{label}</div>
      <div style={{ fontSize: "1.15rem", fontWeight: 600, fontVariantNumeric: "tabular-nums", color: color ?? "var(--text)" }}>
        {value}
      </div>
    </div>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function PerformancePage() {
  const [trades, setTrades] = useState<Trade[]>([])

  const load = useCallback(() =>
    supabase.from("trades").select("*")
      .not("closed_at", "is", null)
      .order("closed_at", { ascending: true })
      .then(({ data }) => data && setTrades(data as Trade[])), [])

  useEffect(() => {
    load()
    const ch = supabase.channel("perf-rt")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "trades" }, load)
      .subscribe()
    return () => { supabase.removeChannel(ch) }
  }, [load])

  const stats    = calcStats(trades)
  const equity   = calcEquitySeries(trades)
  const byStrat  = calcStrategyBreakdown(trades)

  const pnlColor = (v: number | null) =>
    v == null ? "var(--muted)" : v >= 0 ? "var(--green)" : "var(--red)"

  const fmt2 = (v: number | null) => v == null ? "—" : fmtPnl(v)
  const fmtPct = (v: number | null) => v == null ? "—" : `${(v * 100).toFixed(1)}%`
  const fmtFactor = (v: number | null) => v == null ? "—" : v.toFixed(2)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>

      {/* ── header ── */}
      <div style={{ borderBottom: "1px solid var(--border)", paddingBottom: "0.85rem" }}>
        <span style={{ fontSize: "0.72rem", fontWeight: 500, letterSpacing: "0.08em" }}>PERFORMANCE</span>
        {trades.length > 0 && (
          <span style={{ fontSize: "0.62rem", color: "var(--muted)", marginLeft: "1rem" }}>
            {trades.length} closed trades
          </span>
        )}
      </div>

      {trades.length === 0 ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "var(--muted)", fontSize: "0.72rem",
          background: "var(--panel)", border: "1px solid var(--border)" }}>
          — no closed trades yet —
        </div>
      ) : (
        <>
          {/* ── Section 1: stats + charts ── */}

          {/* stat boxes */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: "0.6rem" }}>
            <StatBox label="TOTAL P&L"
              value={fmtPnl(stats.totalPnl)}
              color={pnlColor(stats.totalPnl)} />
            <StatBox label="WIN RATE"
              value={fmtPct(stats.winRate)}
              color={(stats.winRate ?? 0) >= 0.5 ? "var(--green)" : "var(--red)"} />
            <StatBox label="TRADES" value={String(stats.total)} />
            <StatBox label="PROFIT FACTOR"
              value={fmtFactor(stats.profitFactor)}
              color={(stats.profitFactor ?? 0) >= 1.5 ? "var(--green)"
                   : (stats.profitFactor ?? 0) >= 1   ? "var(--accent)"
                   : "var(--red)"} />
            <StatBox label="AVG WIN"
              value={stats.avgWin != null ? fmtPnl(stats.avgWin) : "—"}
              color="var(--green)" />
            <StatBox label="AVG LOSS"
              value={stats.avgLoss != null ? fmtPnl(stats.avgLoss) : "—"}
              color="var(--red)" />
          </div>

          {/* equity curve */}
          <div style={{ background: "var(--panel)", border: "1px solid var(--border)", padding: "1rem" }}>
            <div style={{ fontSize: "0.6rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.75rem" }}>
              EQUITY CURVE
            </div>
            <ResponsiveContainer width="100%" height={180}>
              <AreaChart data={equity} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                <defs>
                  <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="var(--teal)" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="var(--teal)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="label" tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }}
                  axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }}
                  axisLine={false} tickLine={false} width={48}
                  tickFormatter={v => `$${v.toFixed(0)}`} />
                <Tooltip {...tooltipStyle} formatter={(v: number) => [`$${v.toFixed(2)}`, "Cumulative P&L"]} />
                <ReferenceLine y={0} stroke="var(--border-hi)" strokeDasharray="4 2" />
                <Area type="monotone" dataKey="cumPnl" stroke="var(--teal)"
                  fill="url(#eqGrad)" dot={false} strokeWidth={1.5} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* per-trade P&L bars */}
          <div style={{ background: "var(--panel)", border: "1px solid var(--border)", padding: "1rem" }}>
            <div style={{ fontSize: "0.6rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.75rem" }}>
              P&amp;L PER TRADE
            </div>
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={equity} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                <XAxis dataKey="label" tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }}
                  axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }}
                  axisLine={false} tickLine={false} width={48}
                  tickFormatter={v => `$${v.toFixed(0)}`} />
                <Tooltip {...tooltipStyle} formatter={(v: number) => [`$${v.toFixed(2)}`, "P&L"]} />
                <ReferenceLine y={0} stroke="var(--border-hi)" strokeDasharray="4 2" />
                <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
                  {equity.map((e, i) => (
                    <Cell key={i} fill={e.pnl >= 0 ? "var(--green)" : "var(--red)"} opacity={0.75} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* ── Section 2: strategy breakdown ── */}
          <div style={{ background: "var(--panel)", border: "1px solid var(--border)", overflow: "hidden" }}>
            <div style={{ padding: "0.75rem 1rem", borderBottom: "1px solid var(--border)",
              fontSize: "0.6rem", letterSpacing: "0.12em", color: "var(--muted)" }}>
              BY STRATEGY
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["STRATEGY", "TRADES", "WIN RATE", "TOTAL P&L", "AVG WIN", "AVG LOSS", "PROFIT FACTOR"].map(h => (
                    <th key={h} style={{ padding: "0.5rem 0.75rem", fontSize: "0.58rem", fontWeight: 500,
                      letterSpacing: "0.1em", color: "var(--muted)", textAlign: "left", whiteSpace: "nowrap" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {byStrat.map((s, i) => (
                  <tr key={s.strategy} style={{ borderTop: i === 0 ? "none" : "1px solid var(--border)" }}>
                    <td style={{ padding: "0.55rem 0.75rem", fontWeight: 600, fontSize: "0.75rem" }}>{s.strategy}</td>
                    <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem", color: "var(--sub)" }}>{s.trades}</td>
                    <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem",
                      color: s.winRate >= 0.5 ? "var(--green)" : "var(--red)" }}>
                      {fmtPct(s.winRate)}
                    </td>
                    <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.78rem", fontWeight: 600,
                      fontVariantNumeric: "tabular-nums", color: pnlColor(s.totalPnl) }}>
                      {fmt2(s.totalPnl)}
                    </td>
                    <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem", color: "var(--green)" }}>
                      {fmt2(s.avgWin)}
                    </td>
                    <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem", color: "var(--red)" }}>
                      {fmt2(s.avgLoss)}
                    </td>
                    <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem",
                      color: (s.profitFactor ?? 0) >= 1 ? "var(--green)" : "var(--red)" }}>
                      {fmtFactor(s.profitFactor)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify the build passes**

Run: `cd "C:\Users\jrwal\OneDrive\Documents\Algobot\dashboard" && npm run build 2>&1 | tail -10`
Expected: clean compile, `/performance` in the route list, no TypeScript errors.

- [ ] **Step 3: Screenshot the page to verify it renders**

Run: `cd "C:\Users\jrwal\OneDrive\Documents\Algobot\dashboard" && node -e "
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.setViewportSize({ width: 1400, height: 900 });
  await p.goto('http://localhost:3000/performance', { waitUntil: 'networkidle', timeout: 15000 });
  await p.waitForTimeout(2000);
  await p.screenshot({ path: 'C:/tmp/perf_new.png' });
  console.log('screenshot saved');
  await b.close();
})().catch(e => { console.error(e.message); process.exit(1); });
"`

Then read `C:/tmp/perf_new.png` to verify:
- Stat boxes row visible with real numbers (not all "—")
- Equity curve chart renders with a line (not empty)
- P&L per trade bar chart visible with green/red bars
- BY STRATEGY table has an "unknown" row with real stats

If the dev server isn't running on port 3000, start it first:
`cd "C:\Users\jrwal\OneDrive\Documents\Algobot\dashboard" && npm run dev > dev.log 2>&1 &`
then wait 3s and retry the screenshot.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/performance/page.tsx
git commit -m "feat(perf): rebuild performance page from trades table

Replaces performance_daily (0 rows) with live computation from trades.
Three sections: stat boxes (total P&L, win rate, trades, profit factor,
avg win/loss), equity curve + per-trade P&L bars (recharts), strategy
breakdown table sorted by P&L. Realtime INSERT subscription keeps it
live. Profit factor shows '--' when no losses to avoid divide-by-zero."
```

- [ ] **Step 5: Push**

```bash
git push origin main
```

---

## Self-Review Notes

**Spec coverage:**
- ✅ Data from `trades` (not `performance_daily`) — Task 1 query
- ✅ Realtime INSERT subscription — Task 2 `useEffect`
- ✅ 6 stat boxes: Total P&L, Win Rate, Trades, Profit Factor, Avg Win, Avg Loss — Task 2
- ✅ Equity curve (AreaChart, per-trade x-axis, zero reference line) — Task 2
- ✅ Per-trade P&L bars (BarChart, green/red cells) — Task 2
- ✅ Strategy breakdown table sorted by P&L descending, "unknown" as normal row — Task 2
- ✅ Profit factor shows "—" when no losses — `calcStats` / `calcStrategyBreakdown`
- ✅ Empty state renders message not crash — Task 2 early return
- ✅ `npm run build` verification — both tasks

**No placeholders found.**

**Type consistency:** `Trade` used consistently from `@/lib/types`, all helper return shapes match the JSX consumers.
