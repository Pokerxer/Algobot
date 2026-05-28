"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import type { BotStatus, Position, RegimeSnapshot } from "@/lib/types"

const card: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border)",
  borderRadius: 8, padding: "1.25rem",
}

function StatusPill({ status }: { status: string }) {
  const color = status === "RUNNING" ? "var(--green)" : status === "ERROR" ? "var(--red)" : "var(--muted)"
  return (
    <span style={{ fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: 99, border: `1px solid ${color}`, color }}>
      {status}
    </span>
  )
}

function RegimeChip({ regime }: { regime: string }) {
  const color = regime.startsWith("TRENDING") ? "var(--blue)" : regime === "RANGING" ? "var(--yellow)" : "var(--muted)"
  return <span style={{ fontSize: "0.75rem", color }}>{regime}</span>
}

export default function Overview() {
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [regimes, setRegimes] = useState<RegimeSnapshot[]>([])

  useEffect(() => {
    supabase.from("bot_status").select("*").order("id").limit(1).single()
      .then(({ data }) => data && setBotStatus(data as BotStatus))

    supabase.from("positions").select("*").order("opened_at", { ascending: false })
      .then(({ data }) => data && setPositions(data as Position[]))

    supabase.from("regime_snapshots").select("*").order("recorded_at", { ascending: false }).limit(50)
      .then(({ data }) => {
        if (!data) return
        const latest: Record<string, RegimeSnapshot> = {}
        ;(data as RegimeSnapshot[]).forEach(r => { if (!latest[r.instrument]) latest[r.instrument] = r })
        setRegimes(Object.values(latest))
      })

    const ch = supabase.channel("overview")
      .on("postgres_changes", { event: "*", schema: "public", table: "bot_status" },
        ({ new: row }) => setBotStatus(row as BotStatus))
      .on("postgres_changes", { event: "*", schema: "public", table: "positions" },
        () => supabase.from("positions").select("*").order("opened_at", { ascending: false })
          .then(({ data }) => data && setPositions(data as Position[])))
      .subscribe()

    return () => { supabase.removeChannel(ch) }
  }, [])

  const totalPnl = positions.reduce((s, p) => s + (p.profit ?? 0), 0)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <h1 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Overview</h1>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1rem" }}>
        <div style={card}>
          <div style={{ fontSize: "0.7rem", color: "var(--muted)", marginBottom: "0.5rem" }}>BOT STATUS</div>
          {botStatus ? (
            <>
              <StatusPill status={botStatus.status} />
              <div style={{ fontSize: "0.72rem", color: "var(--muted)", marginTop: "0.5rem" }}>
                heartbeat {botStatus.last_heartbeat ? new Date(botStatus.last_heartbeat).toLocaleTimeString() : "—"}
              </div>
            </>
          ) : <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>offline</span>}
        </div>
        <div style={card}>
          <div style={{ fontSize: "0.7rem", color: "var(--muted)", marginBottom: "0.5rem" }}>OPEN POSITIONS</div>
          <div style={{ fontSize: "2rem", fontWeight: 700 }}>{positions.length}</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: "0.7rem", color: "var(--muted)", marginBottom: "0.5rem" }}>UNREALIZED P&amp;L</div>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: totalPnl >= 0 ? "var(--green)" : "var(--red)" }}>
            {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(2)}
          </div>
        </div>
      </div>

      {regimes.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: "0.7rem", color: "var(--muted)", marginBottom: "0.75rem" }}>CURRENT REGIMES</div>
          <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
            {regimes.map(r => (
              <div key={r.instrument} style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>{r.instrument}</span>
                <RegimeChip regime={r.regime} />
                {r.adx != null && <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>ADX {r.adx.toFixed(1)}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {positions.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: "0.7rem", color: "var(--muted)", marginBottom: "0.75rem" }}>POSITIONS</div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
            <thead>
              <tr style={{ color: "var(--muted)", textAlign: "left" }}>
                {["Instrument", "Dir", "Entry", "Current", "Volume", "P&L", "Strategy"].map(h => (
                  <th key={h} style={{ padding: "0.3rem 0.5rem", fontWeight: 400 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map(p => (
                <tr key={p.ticket} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "0.4rem 0.5rem" }}>{p.instrument}</td>
                  <td style={{ padding: "0.4rem 0.5rem", color: p.direction === "BUY" ? "var(--green)" : "var(--red)" }}>{p.direction}</td>
                  <td style={{ padding: "0.4rem 0.5rem" }}>{p.entry_price}</td>
                  <td style={{ padding: "0.4rem 0.5rem" }}>{p.current_price ?? "—"}</td>
                  <td style={{ padding: "0.4rem 0.5rem" }}>{p.volume}</td>
                  <td style={{ padding: "0.4rem 0.5rem", color: (p.profit ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                    {p.profit != null ? `${p.profit >= 0 ? "+" : ""}${p.profit.toFixed(2)}` : "—"}
                  </td>
                  <td style={{ padding: "0.4rem 0.5rem", color: "var(--muted)" }}>{p.strategy ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {positions.length === 0 && regimes.length === 0 && (
        <div style={{ ...card, color: "var(--muted)", fontSize: "0.85rem" }}>
          No live data yet — start the bot to populate this dashboard.
        </div>
      )}
    </div>
  )
}
