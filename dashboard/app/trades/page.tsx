"use client"
import { useEffect, useState, useMemo } from "react"
import { supabase } from "@/lib/supabase"
import type { Trade } from "@/lib/types"
import { fmtPrice, fmtPnl, fmtDur, fmtTime } from "@/lib/fmt"

function StatBox({ label, value, sub, color }: { label: string, value: string, sub?: string, color?: string }) {
  return (
    <div style={{
      background: "var(--panel)", border: "1px solid var(--border)",
      padding: "0.75rem 1rem", display: "flex", flexDirection: "column", gap: "0.2rem",
    }}>
      <div style={{ fontSize: "0.58rem", letterSpacing: "0.12em", color: "var(--muted)" }}>{label}</div>
      <div style={{ fontSize: "1.15rem", fontWeight: 600, fontVariantNumeric: "tabular-nums", color: color ?? "var(--text)" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: "0.6rem", color: "var(--dim)" }}>{sub}</div>}
    </div>
  )
}

function Pill({ children, color, bg }: { children: React.ReactNode, color: string, bg: string }) {
  return (
    <span style={{ fontSize: "0.62rem", fontWeight: 700, padding: "0.1rem 0.35rem", background: bg, color, letterSpacing: "0.04em" }}>
      {children}
    </span>
  )
}

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [filter, setFilter] = useState("ALL")

  const load = () =>
    supabase.from("trades").select("*").order("closed_at", { ascending: false }).limit(500)
      .then(({ data }) => data && setTrades(data as Trade[]))

  useEffect(() => {
    load()
    const ch = supabase.channel("trades-rt")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "trades" }, load)
      .subscribe()
    return () => { supabase.removeChannel(ch) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const instruments = useMemo(() => ["ALL", ...Array.from(new Set(trades.map(t => t.instrument)))], [trades])
  const visible = filter === "ALL" ? trades : trades.filter(t => t.instrument === filter)

  const stats = useMemo(() => {
    const closed = visible.filter(t => t.profit != null)
    if (!closed.length) return null
    const wins = closed.filter(t => (t.profit ?? 0) > 0)
    const losses = closed.filter(t => (t.profit ?? 0) < 0)
    const totalPnl = closed.reduce((s, t) => s + (t.profit ?? 0), 0)
    const avgWin = wins.length ? wins.reduce((s, t) => s + (t.profit ?? 0), 0) / wins.length : 0
    const avgLoss = losses.length ? losses.reduce((s, t) => s + (t.profit ?? 0), 0) / losses.length : 0
    const pf = Math.abs(avgLoss) > 0 ? (avgWin * wins.length) / (Math.abs(avgLoss) * losses.length) : Infinity
    const expectancy = totalPnl / closed.length
    return { count: closed.length, wr: wins.length / closed.length, totalPnl, avgWin, avgLoss, pf, expectancy }
  }, [visible])

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: "1.25rem", borderBottom: "1px solid var(--border)", paddingBottom: "0.85rem", flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.72rem", fontWeight: 500, letterSpacing: "0.08em" }}>TRADE HISTORY</span>
        {stats && <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>{stats.count} trades</span>}
        <div style={{ marginLeft: "auto", display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
          {instruments.map(inst => (
            <button key={inst} onClick={() => setFilter(inst)} style={{
              fontSize: "0.62rem", padding: "0.2rem 0.55rem",
              border: `1px solid ${filter === inst ? "var(--accent)" : "var(--border)"}`,
              background: filter === inst ? "var(--accent-dim)" : "transparent",
              color: filter === inst ? "var(--accent)" : "var(--muted)",
              letterSpacing: "0.06em",
            }}>{inst}</button>
          ))}
        </div>
      </div>

      {/* Stats grid */}
      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: "0.6rem" }}>
          <StatBox label="WIN RATE" value={`${(stats.wr * 100).toFixed(1)}%`}
            color={stats.wr >= 0.5 ? "var(--green)" : "var(--red)"} />
          <StatBox label="TOTAL P&L" value={fmtPnl(stats.totalPnl)} sub="USD"
            color={stats.totalPnl >= 0 ? "var(--green)" : "var(--red)"} />
          <StatBox label="AVG WIN" value={`+${stats.avgWin.toFixed(2)}`} color="var(--green)" />
          <StatBox label="AVG LOSS" value={stats.avgLoss.toFixed(2)} color="var(--red)" />
          <StatBox label="PROFIT FACTOR"
            value={isFinite(stats.pf) ? stats.pf.toFixed(2) : "∞"}
            color={stats.pf >= 1.5 ? "var(--green)" : stats.pf >= 1 ? "var(--accent)" : "var(--red)"} />
          <StatBox label="EXPECTANCY" value={fmtPnl(stats.expectancy)} sub="per trade"
            color={stats.expectancy >= 0 ? "var(--green)" : "var(--red)"} />
          <StatBox label="TRADES" value={String(stats.count)} />
        </div>
      )}

      {/* Table */}
      <div style={{ background: "var(--panel)", border: "1px solid var(--border)", overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["RES", "CLOSED", "INSTRUMENT", "DIR", "ENTRY", "EXIT", "VOL", "P&L", "DUR", "STRATEGY", "AI", "REGIME"].map(h => (
                <th key={h} style={{
                  padding: "0.5rem 0.75rem", fontSize: "0.58rem", fontWeight: 500,
                  letterSpacing: "0.1em", color: "var(--muted)", textAlign: "left", whiteSpace: "nowrap",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((t, i) => {
              const win = (t.profit ?? 0) > 0
              const loss = (t.profit ?? 0) < 0
              return (
                <tr key={t.id} className="fadein" style={{
                  borderTop: i === 0 ? "none" : "1px solid var(--border)",
                  background: win ? "var(--green-dim)" : loss ? "var(--red-dim)" : "transparent",
                  animationDelay: `${Math.min(i, 20) * 0.02}s`,
                }}>
                  <td style={{ padding: "0.6rem 0.75rem" }}>
                    {t.profit != null && (
                      win ? <Pill color="var(--green)" bg="rgba(0,200,122,0.15)">WIN</Pill>
                      : loss ? <Pill color="var(--red)" bg="rgba(232,64,64,0.15)">LOSS</Pill>
                      : <Pill color="var(--muted)" bg="var(--dim)">BE</Pill>
                    )}
                  </td>
                  <td style={{ padding: "0.6rem 0.75rem", fontSize: "0.65rem", color: "var(--muted)", whiteSpace: "nowrap" }}>
                    {fmtTime(t.closed_at, { date: true })}
                  </td>
                  <td style={{ padding: "0.6rem 0.75rem", fontWeight: 700, fontSize: "0.82rem" }}>{t.instrument}</td>
                  <td style={{ padding: "0.6rem 0.75rem" }}>
                    <Pill
                      color={t.direction === "BUY" ? "var(--green)" : "var(--red)"}
                      bg={t.direction === "BUY" ? "rgba(0,200,122,0.12)" : "rgba(232,64,64,0.12)"}
                    >{t.direction ?? "—"}</Pill>
                  </td>
                  <td style={{ padding: "0.6rem 0.75rem", fontVariantNumeric: "tabular-nums", fontSize: "0.75rem" }}>
                    {fmtPrice(t.entry_price, t.instrument)}
                  </td>
                  <td style={{ padding: "0.6rem 0.75rem", fontVariantNumeric: "tabular-nums", fontSize: "0.75rem" }}>
                    {fmtPrice(t.exit_price, t.instrument)}
                  </td>
                  <td style={{ padding: "0.6rem 0.75rem", fontSize: "0.72rem", color: "var(--sub)" }}>{t.volume ?? "—"}</td>
                  <td style={{ padding: "0.6rem 0.75rem", fontWeight: 700, fontVariantNumeric: "tabular-nums", fontSize: "0.82rem",
                    color: win ? "var(--green)" : loss ? "var(--red)" : "var(--sub)" }}>
                    {fmtPnl(t.profit)}
                  </td>
                  <td style={{ padding: "0.6rem 0.75rem", fontSize: "0.68rem", color: "var(--muted)" }}>{fmtDur(t.duration_minutes)}</td>
                  <td style={{ padding: "0.6rem 0.75rem", fontSize: "0.68rem", color: "var(--sub)" }}>{t.strategy ?? "—"}</td>
                  <td style={{ padding: "0.6rem 0.75rem" }}>
                    {t.ai_decision && (
                      <Pill
                        color={t.ai_decision === "APPROVE" ? "var(--green)" : t.ai_decision === "VETO" ? "var(--red)" : "var(--yellow)"}
                        bg={t.ai_decision === "APPROVE" ? "rgba(0,200,122,0.12)" : t.ai_decision === "VETO" ? "rgba(232,64,64,0.12)" : "rgba(232,168,64,0.12)"}
                      >{t.ai_decision}</Pill>
                    )}
                    {!t.ai_decision && <span style={{ color: "var(--muted)" }}>—</span>}
                  </td>
                  <td style={{ padding: "0.6rem 0.75rem", fontSize: "0.65rem", color: "var(--muted)" }}>{t.regime ?? "—"}</td>
                </tr>
              )
            })}
            {visible.length === 0 && (
              <tr><td colSpan={12} style={{ padding: "2.5rem", color: "var(--muted)", textAlign: "center", fontSize: "0.72rem" }}>
                — no closed trades yet. they appear here once a position closes via SL, TP, or trailing stop —
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
