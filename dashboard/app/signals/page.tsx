"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import type { Signal } from "@/lib/types"

const card: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "1.25rem",
}

function AiBadge({ decision }: { decision: string | null }) {
  if (!decision) return null
  const color = decision === "APPROVE" ? "var(--green)" : decision === "VETO" ? "var(--red)" : "var(--yellow)"
  return <span style={{ fontSize: "0.7rem", padding: "0.15rem 0.45rem", borderRadius: 4, border: `1px solid ${color}`, color }}>{decision}</span>
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([])

  const load = () =>
    supabase.from("signals").select("*").order("created_at", { ascending: false }).limit(100)
      .then(({ data }) => data && setSignals(data as Signal[]))

  useEffect(() => {
    load()
    const ch = supabase.channel("signals-feed")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "signals" }, load)
      .subscribe()
    return () => { supabase.removeChannel(ch) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <h1 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Signals</h1>
      <div style={card}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
          <thead>
            <tr style={{ color: "var(--muted)", textAlign: "left" }}>
              {["Time", "Instrument", "Dir", "Confidence", "Regime", "Strategy", "AI", "Executed"].map(h => (
                <th key={h} style={{ padding: "0.3rem 0.5rem", fontWeight: 400 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {signals.map(s => (
              <tr key={s.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)", whiteSpace: "nowrap" }}>
                  {new Date(s.created_at).toLocaleTimeString()}
                </td>
                <td style={{ padding: "0.4rem 0.5rem", fontWeight: 600 }}>{s.instrument}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: s.direction === "BUY" ? "var(--green)" : "var(--red)" }}>{s.direction}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{s.confidence != null ? `${(s.confidence * 100).toFixed(0)}%` : "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)", fontSize: "0.75rem" }}>{s.regime ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)" }}>{s.strategy ?? "—"}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}><AiBadge decision={s.ai_decision} /></td>
                <td style={{ padding: "0.4rem 0.5rem", color: s.executed ? "var(--green)" : "var(--muted)" }}>
                  {s.executed ? "YES" : "no"}
                </td>
              </tr>
            ))}
            {signals.length === 0 && (
              <tr><td colSpan={8} style={{ padding: "1rem 0.5rem", color: "var(--muted)" }}>No signals yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
