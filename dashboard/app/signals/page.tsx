"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import type { Signal } from "@/lib/types"
import { fmtTime } from "@/lib/fmt"

function Pill({ children, color, bg }: { children: React.ReactNode, color: string, bg: string }) {
  return (
    <span style={{ fontSize: "0.62rem", fontWeight: 700, padding: "0.1rem 0.35rem", background: bg, color, letterSpacing: "0.04em" }}>
      {children}
    </span>
  )
}

function ConfBar({ value }: { value: number }) {
  const color = value >= 0.75 ? "var(--green)" : value >= 0.5 ? "var(--accent)" : "var(--muted)"
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
      <div style={{ width: 50, height: 3, background: "var(--border-hi)", position: "relative" }}>
        <div style={{ width: `${value * 100}%`, height: "100%", background: color }} />
      </div>
      <span style={{ fontSize: "0.65rem", color: "var(--sub)", fontVariantNumeric: "tabular-nums" }}>
        {(value * 100).toFixed(0)}%
      </span>
    </div>
  )
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([])

  const load = () =>
    supabase.from("signals").select("*").order("created_at", { ascending: false }).limit(200)
      .then(({ data }) => data && setSignals(data as Signal[]))

  useEffect(() => {
    load()
    const ch = supabase.channel("signals-rt")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "signals" }, load)
      .subscribe()
    return () => { supabase.removeChannel(ch) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const executed = signals.filter(s => s.executed).length
  const vetoed = signals.filter(s => s.ai_decision === "VETO").length

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>

      <div style={{ display: "flex", alignItems: "center", gap: "1.5rem", borderBottom: "1px solid var(--border)", paddingBottom: "0.85rem" }}>
        <span style={{ fontSize: "0.72rem", fontWeight: 500, letterSpacing: "0.08em" }}>SIGNAL FEED</span>
        <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>{signals.length} evaluated</span>
        {executed > 0 && <span style={{ fontSize: "0.65rem", color: "var(--green)" }}>{executed} executed</span>}
        {vetoed > 0 && <span style={{ fontSize: "0.65rem", color: "var(--red)" }}>{vetoed} vetoed</span>}
      </div>

      <div style={{ background: "var(--panel)", border: "1px solid var(--border)", overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["TIME", "INSTRUMENT", "DIR", "CONFIDENCE", "REGIME", "STRATEGY", "AI DECISION", "REASONING", "EXEC"].map(h => (
                <th key={h} style={{
                  padding: "0.5rem 0.75rem", fontSize: "0.58rem", fontWeight: 500,
                  letterSpacing: "0.1em", color: "var(--muted)", textAlign: "left", whiteSpace: "nowrap",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {signals.map((s, i) => {
              const rowBg = s.executed ? "rgba(0,200,122,0.04)" : "transparent"
              return (
                <tr key={s.id} className="fadein" style={{
                  borderTop: i === 0 ? "none" : "1px solid var(--border)",
                  background: rowBg,
                  animationDelay: `${Math.min(i, 20) * 0.02}s`,
                }}>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.65rem", color: "var(--muted)", whiteSpace: "nowrap" }}>
                    {fmtTime(s.created_at, { date: true })}
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem", fontWeight: 700, fontSize: "0.82rem" }}>{s.instrument}</td>
                  <td style={{ padding: "0.55rem 0.75rem" }}>
                    <Pill
                      color={s.direction === "BUY" ? "var(--green)" : "var(--red)"}
                      bg={s.direction === "BUY" ? "rgba(0,200,122,0.12)" : "rgba(232,64,64,0.12)"}
                    >{s.direction}</Pill>
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem" }}>
                    {s.confidence != null ? <ConfBar value={s.confidence} /> : <span style={{ color: "var(--muted)" }}>—</span>}
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.68rem" }}>
                    <span style={{
                      color: (s.regime ?? "").startsWith("TRENDING") ? ((s.regime ?? "").includes("UP") ? "var(--green)" : "var(--red)")
                        : s.regime === "RANGING" ? "var(--accent)" : "var(--muted)"
                    }}>
                      {(s.regime ?? "—").replace("_", " ")}
                    </span>
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.68rem", color: "var(--sub)" }}>{s.strategy ?? "—"}</td>
                  <td style={{ padding: "0.55rem 0.75rem" }}>
                    {s.ai_decision ? (
                      <Pill
                        color={s.ai_decision === "APPROVE" ? "var(--green)" : s.ai_decision === "VETO" ? "var(--red)" : "var(--yellow)"}
                        bg={s.ai_decision === "APPROVE" ? "rgba(0,200,122,0.12)" : s.ai_decision === "VETO" ? "rgba(232,64,64,0.12)" : "rgba(232,168,64,0.12)"}
                      >{s.ai_decision}</Pill>
                    ) : <span style={{ color: "var(--muted)" }}>—</span>}
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem", fontSize: "0.62rem", color: "var(--muted)", maxWidth: 260,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {s.ai_reasoning ?? "—"}
                  </td>
                  <td style={{ padding: "0.55rem 0.75rem" }}>
                    {s.executed
                      ? <Pill color="var(--accent)" bg="var(--accent-dim)">EXEC</Pill>
                      : <span style={{ fontSize: "0.62rem", color: "var(--muted)" }}>skip</span>}
                  </td>
                </tr>
              )
            })}
            {signals.length === 0 && (
              <tr><td colSpan={9} style={{ padding: "2.5rem", color: "var(--muted)", textAlign: "center", fontSize: "0.72rem" }}>
                — awaiting signals —
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
