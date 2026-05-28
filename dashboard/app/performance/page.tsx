"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import type { PerformanceDaily } from "@/lib/types"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts"

const card: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "1.25rem",
}

export default function PerformancePage() {
  const [rows, setRows] = useState<PerformanceDaily[]>([])

  useEffect(() => {
    supabase.from("performance_daily").select("*").order("date", { ascending: true }).limit(90)
      .then(({ data }) => data && setRows(data as PerformanceDaily[]))
  }, [])

  const latest = rows[rows.length - 1]
  const chartData = rows.map(r => ({ date: r.date.slice(5), balance: r.balance, profit: r.profit }))

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <h1 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Performance</h1>

      {latest && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem" }}>
          {[
            { label: "BALANCE", value: latest.balance != null ? `$${latest.balance.toFixed(2)}` : "—" },
            { label: "WIN RATE", value: latest.win_rate != null ? `${(latest.win_rate * 100).toFixed(1)}%` : "—" },
            { label: "TODAY P&L", value: latest.profit != null ? `${latest.profit >= 0 ? "+" : ""}${latest.profit.toFixed(2)}` : "—", pnl: latest.profit },
            { label: "MAX DRAWDOWN", value: latest.drawdown != null ? `${(latest.drawdown * 100).toFixed(2)}%` : "—" },
          ].map(({ label, value, pnl }) => (
            <div key={label} style={card}>
              <div style={{ fontSize: "0.7rem", color: "var(--muted)", marginBottom: "0.5rem" }}>{label}</div>
              <div style={{ fontSize: "1.5rem", fontWeight: 700, color: pnl != null ? (pnl >= 0 ? "var(--green)" : "var(--red)") : "var(--text)" }}>
                {value}
              </div>
            </div>
          ))}
        </div>
      )}

      {chartData.length > 1 && (
        <div style={card}>
          <div style={{ fontSize: "0.7rem", color: "var(--muted)", marginBottom: "1rem" }}>EQUITY CURVE (90d)</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} width={60} />
              <Tooltip
                contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: "var(--muted)" }}
              />
              <ReferenceLine y={0} stroke="var(--border)" />
              <Line type="monotone" dataKey="balance" stroke="var(--blue)" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div style={card}>
        <div style={{ fontSize: "0.7rem", color: "var(--muted)", marginBottom: "0.75rem" }}>DAILY LOG</div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
          <thead>
            <tr style={{ color: "var(--muted)", textAlign: "left" }}>
              {["Date", "Trades", "Win Rate", "P&L", "Drawdown", "Balance", "Sharpe"].map(h => (
                <th key={h} style={{ padding: "0.3rem 0.5rem", fontWeight: 400 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...rows].reverse().map(r => (
              <tr key={r.date} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "0.4rem 0.5rem" }}>{r.date}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{r.total_trades ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: (r.profit ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                  {r.profit != null ? `${r.profit >= 0 ? "+" : ""}${r.profit.toFixed(2)}` : "—"}
                </td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)" }}>
                  {r.drawdown != null ? `${(r.drawdown * 100).toFixed(2)}%` : "—"}
                </td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{r.balance != null ? `$${r.balance.toFixed(2)}` : "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)" }}>{r.sharpe?.toFixed(2) ?? "—"}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={7} style={{ padding: "1rem 0.5rem", color: "var(--muted)" }}>No performance data yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
