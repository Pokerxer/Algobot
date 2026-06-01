"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import type { PerformanceDaily } from "@/lib/types"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Area, AreaChart } from "recharts"
import { fmtPnl } from "@/lib/fmt"

function StatBox({ label, value, sub, color }: { label: string, value: string, sub?: string, color?: string }) {
  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--border)", padding: "0.85rem 1rem" }}>
      <div style={{ fontSize: "0.58rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.3rem" }}>{label}</div>
      <div style={{ fontSize: "1.3rem", fontWeight: 600, fontVariantNumeric: "tabular-nums", color: color ?? "var(--text)" }}>{value}</div>
      {sub && <div style={{ fontSize: "0.6rem", color: "var(--dim)", marginTop: "0.15rem" }}>{sub}</div>}
    </div>
  )
}

const tooltipStyle = {
  contentStyle: {
    background: "var(--panel)", border: "1px solid var(--border)",
    borderRadius: 0, fontSize: 11, fontFamily: "'IBM Plex Mono', monospace",
  },
  labelStyle: { color: "var(--muted)" },
  itemStyle: { color: "var(--text)" },
}

export default function PerformancePage() {
  const [rows, setRows] = useState<PerformanceDaily[]>([])

  useEffect(() => {
    supabase.from("performance_daily").select("*").order("date", { ascending: true }).limit(90)
      .then(({ data }) => data && setRows(data as PerformanceDaily[]))
  }, [])

  const latest = rows[rows.length - 1]

  const balanceData = rows.map(r => ({
    d: r.date.slice(5),
    balance: r.balance,
    profit: r.profit,
  }))

  const winRateData = rows.map(r => ({
    d: r.date.slice(5),
    wr: r.win_rate != null ? parseFloat((r.win_rate * 100).toFixed(1)) : null,
  }))

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>

      <div style={{ borderBottom: "1px solid var(--border)", paddingBottom: "0.85rem" }}>
        <span style={{ fontSize: "0.72rem", fontWeight: 500, letterSpacing: "0.08em" }}>PERFORMANCE</span>
      </div>

      {/* Latest stats */}
      {latest && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: "0.6rem" }}>
          <StatBox label="BALANCE" value={latest.balance != null ? `$${latest.balance.toFixed(2)}` : "—"} />
          <StatBox label="WIN RATE"
            value={latest.win_rate != null ? `${(latest.win_rate * 100).toFixed(1)}%` : "—"}
            color={(latest.win_rate ?? 0) >= 0.5 ? "var(--green)" : "var(--red)"} />
          <StatBox label="TODAY P&L"
            value={latest.profit != null ? fmtPnl(latest.profit) : "—"}
            sub="USD"
            color={(latest.profit ?? 0) >= 0 ? "var(--green)" : "var(--red)"} />
          <StatBox label="MAX DRAWDOWN"
            value={latest.drawdown != null ? `${(latest.drawdown * 100).toFixed(2)}%` : "—"}
            color={(latest.drawdown ?? 0) < 0.03 ? "var(--green)" : (latest.drawdown ?? 0) < 0.05 ? "var(--accent)" : "var(--red)"} />
          <StatBox label="SHARPE"
            value={latest.sharpe?.toFixed(2) ?? "—"}
            color={(latest.sharpe ?? 0) >= 1 ? "var(--green)" : (latest.sharpe ?? 0) >= 0 ? "var(--accent)" : "var(--red)"} />
          <StatBox label="TRADES TODAY" value={latest.total_trades?.toString() ?? "—"} />
        </div>
      )}

      {/* Charts */}
      {balanceData.length > 1 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
          <div style={{ background: "var(--panel)", border: "1px solid var(--border)", padding: "1rem" }}>
            <div style={{ fontSize: "0.6rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.75rem" }}>
              EQUITY CURVE
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <AreaChart data={balanceData}>
                <defs>
                  <linearGradient id="balGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--teal)" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="var(--teal)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="d" tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }} axisLine={false} tickLine={false} width={55} />
                <Tooltip {...tooltipStyle} />
                <Area type="monotone" dataKey="balance" stroke="var(--teal)" fill="url(#balGrad)" dot={false} strokeWidth={1.5} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div style={{ background: "var(--panel)", border: "1px solid var(--border)", padding: "1rem" }}>
            <div style={{ fontSize: "0.6rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.75rem" }}>
              DAILY P&amp;L
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={balanceData}>
                <XAxis dataKey="d" tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }} axisLine={false} tickLine={false} width={40} />
                <Tooltip {...tooltipStyle} />
                <ReferenceLine y={0} stroke="var(--border-hi)" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="profit" stroke="var(--accent)" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {winRateData.length > 1 && (
            <div style={{ background: "var(--panel)", border: "1px solid var(--border)", padding: "1rem", gridColumn: "1/-1" }}>
              <div style={{ fontSize: "0.6rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.75rem" }}>
                WIN RATE TREND
              </div>
              <ResponsiveContainer width="100%" height={120}>
                <LineChart data={winRateData}>
                  <XAxis dataKey="d" tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 9, fill: "var(--muted)", fontFamily: "inherit" }} axisLine={false} tickLine={false} domain={[0, 100]} width={30} unit="%" />
                  <Tooltip {...tooltipStyle} />
                  <ReferenceLine y={50} stroke="var(--border-hi)" strokeDasharray="3 3" />
                  <Line type="monotone" dataKey="wr" stroke="var(--green)" dot={false} strokeWidth={1.5} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* Daily log */}
      <div style={{ background: "var(--panel)", border: "1px solid var(--border)", overflow: "hidden" }}>
        <div style={{ padding: "0.75rem 1rem", borderBottom: "1px solid var(--border)", fontSize: "0.6rem", letterSpacing: "0.12em", color: "var(--muted)" }}>
          DAILY LOG
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["DATE", "TRADES", "WIN RATE", "P&L", "DRAWDOWN", "BALANCE", "SHARPE"].map(h => (
                <th key={h} style={{ padding: "0.5rem 0.75rem", fontSize: "0.58rem", fontWeight: 500, letterSpacing: "0.1em", color: "var(--muted)", textAlign: "left" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...rows].reverse().map((r, i) => {
              const pnl = r.profit ?? 0
              return (
                <tr key={r.date} style={{ borderTop: i === 0 ? "none" : "1px solid var(--border)" }}>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem", fontVariantNumeric: "tabular-nums" }}>{r.date}</td>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem", color: "var(--sub)" }}>{r.total_trades ?? "—"}</td>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem", color: (r.win_rate ?? 0) >= 0.5 ? "var(--green)" : "var(--red)" }}>
                    {r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem", fontWeight: 600, fontVariantNumeric: "tabular-nums", fontSize: "0.78rem",
                    color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                    {fmtPnl(r.profit)}
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem", color: "var(--muted)" }}>
                    {r.drawdown != null ? `${(r.drawdown * 100).toFixed(2)}%` : "—"}
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.75rem", fontVariantNumeric: "tabular-nums" }}>
                    {r.balance != null ? `$${r.balance.toFixed(2)}` : "—"}
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.72rem", color: (r.sharpe ?? 0) >= 1 ? "var(--green)" : "var(--muted)" }}>
                    {r.sharpe?.toFixed(2) ?? "—"}
                  </td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr><td colSpan={7} style={{ padding: "2.5rem", color: "var(--muted)", textAlign: "center", fontSize: "0.72rem" }}>
                — performance data appears here at end of each trading day —
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
