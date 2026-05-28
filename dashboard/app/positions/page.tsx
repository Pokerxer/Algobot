"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import type { Position } from "@/lib/types"

const card: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "1.25rem",
}

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([])

  const load = () =>
    supabase.from("positions").select("*").order("opened_at", { ascending: false })
      .then(({ data }) => data && setPositions(data as Position[]))

  useEffect(() => {
    load()
    const ch = supabase.channel("positions-live")
      .on("postgres_changes", { event: "*", schema: "public", table: "positions" }, load)
      .subscribe()
    return () => { supabase.removeChannel(ch) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const totalPnl = positions.reduce((s, p) => s + (p.profit ?? 0), 0)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "1rem" }}>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Positions</h1>
        <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{positions.length} open</span>
        {positions.length > 0 && (
          <span style={{ fontSize: "0.85rem", color: totalPnl >= 0 ? "var(--green)" : "var(--red)", marginLeft: "auto" }}>
            P&amp;L {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(2)}
          </span>
        )}
      </div>
      <div style={card}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
          <thead>
            <tr style={{ color: "var(--muted)", textAlign: "left" }}>
              {["Ticket", "Instrument", "Dir", "Volume", "Entry", "Current", "SL", "TP", "P&L", "Regime", "Opened"].map(h => (
                <th key={h} style={{ padding: "0.3rem 0.5rem", fontWeight: 400 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map(p => (
              <tr key={p.ticket} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)", fontSize: "0.72rem" }}>{p.ticket}</td>
                <td style={{ padding: "0.4rem 0.5rem", fontWeight: 600 }}>{p.instrument}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: p.direction === "BUY" ? "var(--green)" : "var(--red)" }}>{p.direction}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{p.volume}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{p.entry_price}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{p.current_price ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)" }}>{p.stop_loss ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)" }}>{p.take_profit ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: (p.profit ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                  {p.profit != null ? `${p.profit >= 0 ? "+" : ""}${p.profit.toFixed(2)}` : "—"}
                </td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)", fontSize: "0.75rem" }}>{p.regime ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)", fontSize: "0.72rem" }}>
                  {new Date(p.opened_at).toLocaleString()}
                </td>
              </tr>
            ))}
            {positions.length === 0 && (
              <tr><td colSpan={11} style={{ padding: "1rem 0.5rem", color: "var(--muted)" }}>No open positions.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
