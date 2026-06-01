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

  const stats   = calcStats(trades)
  const equity  = calcEquitySeries(trades)
  const byStrat = calcStrategyBreakdown(trades)

  const pnlColor = (v: number | null) =>
    v == null ? "var(--muted)" : v >= 0 ? "var(--green)" : "var(--red)"

  const fmt2     = (v: number | null) => v == null ? "—" : fmtPnl(v)
  const fmtPct   = (v: number | null) => v == null ? "—" : `${(v * 100).toFixed(1)}%`
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
                  tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                <Tooltip {...tooltipStyle} formatter={(v: unknown) => [`$${(v as number).toFixed(2)}`, "Cumulative P&L"]} />
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
                  tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                <Tooltip {...tooltipStyle} formatter={(v: unknown) => [`$${(v as number).toFixed(2)}`, "P&L"]} />
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
