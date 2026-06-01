"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import type { Position } from "@/lib/types"
import { fmtPrice, fmtPips, fmtPnl, timeAgo } from "@/lib/fmt"

function Label({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: "0.6rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.5rem" }}>{children}</div>
}

function ColH({ children, right }: { children: React.ReactNode, right?: boolean }) {
  return (
    <th style={{
      padding: "0.5rem 0.75rem", fontSize: "0.58rem", fontWeight: 500,
      letterSpacing: "0.1em", color: "var(--muted)", textAlign: right ? "right" : "left",
      whiteSpace: "nowrap",
    }}>{children}</th>
  )
}

function SlTpBar({ pos }: { pos: Position }) {
  if (!pos.stop_loss || !pos.take_profit || !pos.current_price) return null
  const sl = pos.stop_loss, tp = pos.take_profit, cur = pos.current_price, entry = pos.entry_price
  const range = Math.abs(tp - sl)
  if (range === 0) return null
  const isBuy = pos.direction === "BUY"
  const pct = isBuy
    ? Math.max(0, Math.min(1, (cur - sl) / range))
    : Math.max(0, Math.min(1, (sl - cur) / range))
  const color = pct > 0.5 ? "var(--green)" : pct > 0.2 ? "var(--accent)" : "var(--red)"
  return (
    <div style={{ position: "relative", height: 3, background: "var(--border-hi)", marginTop: "0.3rem", width: 80 }}>
      <div style={{ width: `${pct * 100}%`, height: "100%", background: color, transition: "width 0.3s" }} />
      {/* Entry marker */}
      <div style={{
        position: "absolute", top: -1, height: 5, width: 1,
        background: "var(--sub)",
        left: `${Math.max(0, Math.min(100, isBuy ? ((entry - sl) / range * 100) : ((sl - entry) / range * 100)))}%`,
      }} />
    </div>
  )
}

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([])
  const [, setTick] = useState(0)

  const load = () =>
    supabase.from("positions").select("*").order("opened_at", { ascending: false })
      .then(({ data }) => data && setPositions(data as Position[]))

  useEffect(() => {
    load()
    const timer = setInterval(() => setTick(t => t + 1), 30000)
    const ch = supabase.channel("pos-live")
      .on("postgres_changes", { event: "*", schema: "public", table: "positions" }, load)
      .subscribe()
    return () => { supabase.removeChannel(ch); clearInterval(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const totalPnl = positions.reduce((s, p) => s + (p.profit ?? 0), 0)
  const longs = positions.filter(p => p.direction === "BUY").length
  const shorts = positions.filter(p => p.direction === "SELL").length

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>

      {/* Header bar */}
      <div style={{ display: "flex", alignItems: "baseline", gap: "1.5rem", borderBottom: "1px solid var(--border)", paddingBottom: "0.85rem" }}>
        <span style={{ fontSize: "0.72rem", fontWeight: 500, letterSpacing: "0.08em" }}>POSITIONS</span>
        <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>{positions.length} open</span>
        {positions.length > 0 && (
          <>
            <span style={{ fontSize: "0.65rem", color: "var(--green)" }}>L:{longs}</span>
            <span style={{ fontSize: "0.65rem", color: "var(--red)" }}>S:{shorts}</span>
          </>
        )}
        <div style={{ marginLeft: "auto", textAlign: "right" }}>
          <div style={{ fontSize: "0.58rem", color: "var(--muted)", letterSpacing: "0.1em" }}>TOTAL FLOAT P&amp;L</div>
          <div style={{ fontSize: "1.1rem", fontWeight: 600, fontVariantNumeric: "tabular-nums",
            color: totalPnl >= 0 ? "var(--green)" : "var(--red)" }}>
            {fmtPnl(totalPnl)} USD
          </div>
        </div>
      </div>

      <Label>OPEN POSITIONS</Label>
      <div style={{ background: "var(--panel)", border: "1px solid var(--border)", overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <ColH>TICKET</ColH>
              <ColH>INSTRUMENT</ColH>
              <ColH>DIR</ColH>
              <ColH>VOL</ColH>
              <ColH>ENTRY</ColH>
              <ColH>CURRENT</ColH>
              <ColH>STOP LOSS</ColH>
              <ColH>TAKE PROFIT</ColH>
              <ColH right>FLOAT P&amp;L</ColH>
              <ColH>SL/TP RANGE</ColH>
              <ColH>R/R</ColH>
              <ColH>STRATEGY</ColH>
              <ColH>OPEN</ColH>
            </tr>
          </thead>
          <tbody>
            {positions.map((p, i) => {
              const pnl = p.profit ?? 0
              const slDist = p.stop_loss ? Math.abs(p.entry_price - p.stop_loss) : null
              const tpDist = p.take_profit ? Math.abs(p.take_profit - p.entry_price) : null
              const rr = slDist && tpDist && slDist > 0 ? (tpDist / slDist).toFixed(2) : null
              const rrNum = rr ? parseFloat(rr) : null
              return (
                <tr key={p.ticket} className="fadein" style={{
                  borderTop: i === 0 ? "none" : "1px solid var(--border)",
                  background: pnl > 0 ? "var(--green-dim)" : pnl < 0 ? "var(--red-dim)" : "transparent",
                  animationDelay: `${i * 0.05}s`,
                }}>
                  <td style={{ padding: "0.65rem 0.75rem", fontSize: "0.62rem", color: "var(--muted)", fontVariantNumeric: "tabular-nums" }}>
                    #{p.ticket}
                  </td>
                  <td style={{ padding: "0.65rem 0.75rem", fontWeight: 700, fontSize: "0.82rem" }}>{p.instrument}</td>
                  <td style={{ padding: "0.65rem 0.75rem" }}>
                    <span style={{
                      fontSize: "0.62rem", fontWeight: 700, padding: "0.15rem 0.4rem",
                      background: p.direction === "BUY" ? "rgba(0,200,122,0.15)" : "rgba(232,64,64,0.15)",
                      color: p.direction === "BUY" ? "var(--green)" : "var(--red)",
                      letterSpacing: "0.05em",
                    }}>{p.direction}</span>
                  </td>
                  <td style={{ padding: "0.65rem 0.75rem", fontSize: "0.75rem", color: "var(--sub)" }}>{p.volume}</td>
                  <td style={{ padding: "0.65rem 0.75rem", fontVariantNumeric: "tabular-nums", fontSize: "0.78rem" }}>
                    {fmtPrice(p.entry_price, p.instrument)}
                  </td>
                  <td style={{ padding: "0.65rem 0.75rem", fontVariantNumeric: "tabular-nums", fontSize: "0.78rem", fontWeight: 600 }}>
                    {fmtPrice(p.current_price, p.instrument)}
                  </td>
                  <td style={{ padding: "0.65rem 0.75rem", fontSize: "0.72rem" }}>
                    <div style={{ color: "var(--red)", fontVariantNumeric: "tabular-nums" }}>{fmtPrice(p.stop_loss, p.instrument)}</div>
                    {slDist && <div style={{ fontSize: "0.6rem", color: "var(--muted)" }}>{fmtPips(slDist, p.instrument)} pip</div>}
                  </td>
                  <td style={{ padding: "0.65rem 0.75rem", fontSize: "0.72rem" }}>
                    <div style={{ color: "var(--teal)", fontVariantNumeric: "tabular-nums" }}>{fmtPrice(p.take_profit, p.instrument)}</div>
                    {tpDist && <div style={{ fontSize: "0.6rem", color: "var(--muted)" }}>{fmtPips(tpDist, p.instrument)} pip</div>}
                  </td>
                  <td style={{ padding: "0.65rem 0.75rem", textAlign: "right" }}>
                    <div style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums", fontSize: "0.85rem",
                      color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>{fmtPnl(p.profit)}</div>
                  </td>
                  <td style={{ padding: "0.65rem 0.75rem" }}>
                    <SlTpBar pos={p} />
                  </td>
                  <td style={{ padding: "0.65rem 0.75rem" }}>
                    {rr && (
                      <span style={{
                        fontSize: "0.68rem", fontWeight: 600,
                        color: rrNum && rrNum >= 2 ? "var(--green)" : rrNum && rrNum >= 1.5 ? "var(--accent)" : "var(--muted)",
                      }}>{rr}:1</span>
                    )}
                    {!rr && <span style={{ color: "var(--muted)" }}>—</span>}
                  </td>
                  <td style={{ padding: "0.65rem 0.75rem", fontSize: "0.68rem", color: "var(--sub)" }}>{p.strategy ?? "—"}</td>
                  <td style={{ padding: "0.65rem 0.75rem", fontSize: "0.65rem", color: "var(--muted)", whiteSpace: "nowrap" }}>
                    {timeAgo(p.opened_at)}
                    <div style={{ fontSize: "0.58rem", color: "var(--dim)" }}>
                      {new Date(p.opened_at).toLocaleDateString("en-GB")}
                    </div>
                  </td>
                </tr>
              )
            })}
            {positions.length === 0 && (
              <tr><td colSpan={13} style={{ padding: "2rem", color: "var(--muted)", textAlign: "center", fontSize: "0.72rem" }}>
                — no open positions —
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
