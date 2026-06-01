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

// ── placeholder page (replaced in Task 2) ────────────────────────────────────

export default function PerformancePage() {
  return <div style={{ color: "var(--muted)", padding: "2rem" }}>loading…</div>
}
