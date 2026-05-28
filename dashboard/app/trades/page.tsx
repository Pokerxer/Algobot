"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import type { Trade } from "@/lib/types"

const card: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "1.25rem",
}

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([])

  useEffect(() => {
    supabase.from("trades").select("*").order("closed_at", { ascending: false }).limit(200)
      .then(({ data }) => data && setTrades(data as Trade[]))
  }, [])

  const wins = trades.filter(t => (t.profit ?? 0) > 0).length
  const totalPnl = trades.reduce((s, t) => s + (t.profit ?? 0), 0)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "1.5rem" }}>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Trades</h1>
        {trades.length > 0 && (
          <>
            <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{trades.length} closed</span>
            <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
              win rate {((wins / trades.length) * 100).toFixed(0)}%
            </span>
            <span style={{ fontSize: "0.85rem", color: totalPnl >= 0 ? "var(--green)" : "var(--red)", marginLeft: "auto" }}>
              total P&amp;L {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(2)}
            </span>
          </>
        )}
      </div>
      <div style={card}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
          <thead>
            <tr style={{ color: "var(--muted)", textAlign: "left" }}>
              {["Closed", "Instrument", "Dir", "Entry", "Exit", "Volume", "P&L", "Duration", "Strategy", "AI"].map(h => (
                <th key={h} style={{ padding: "0.3rem 0.5rem", fontWeight: 400 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map(t => (
              <tr key={t.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)", fontSize: "0.72rem", whiteSpace: "nowrap" }}>
                  {t.closed_at ? new Date(t.closed_at).toLocaleString() : "—"}
                </td>
                <td style={{ padding: "0.4rem 0.5rem", fontWeight: 600 }}>{t.instrument}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: t.direction === "BUY" ? "var(--green)" : "var(--red)" }}>
                  {t.direction ?? "—"}
                </td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{t.entry_price ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{t.exit_price ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{t.volume ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: (t.profit ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                  {t.profit != null ? `${t.profit >= 0 ? "+" : ""}${t.profit.toFixed(2)}` : "—"}
                </td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)" }}>
                  {t.duration_minutes != null ? `${t.duration_minutes}m` : "—"}
                </td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)" }}>{t.strategy ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)", fontSize: "0.75rem" }}>{t.ai_decision ?? "—"}</td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr><td colSpan={10} style={{ padding: "1rem 0.5rem", color: "var(--muted)" }}>No closed trades yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
