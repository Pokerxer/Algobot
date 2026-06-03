"use client"
import { useEffect, useState, useCallback } from "react"
import { supabase } from "@/lib/supabase"
import type { SignalEvaluation } from "@/lib/types"
import { timeAgo } from "@/lib/fmt"
import { InstrumentDrawer, type DrawerItem } from "@/components/InstrumentDrawer"

const STATUS = {
  signal:   { color: "var(--green)",  label: "SETUP READY" },
  no_setup: { color: "var(--yellow)", label: "NO SETUP" },
  gated:    { color: "var(--muted)",  label: "GATED" },
} as const

function Bar({ value }: { value: number | null }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value))
  const color = pct > 0.66 ? "var(--green)" : pct > 0.33 ? "var(--yellow)" : "var(--dim)"
  return (
    <div style={{ width: 90, height: 4, background: "var(--border-hi)" }}>
      <div style={{ width: `${pct * 100}%`, height: "100%", background: color, transition: "width 0.4s" }} />
    </div>
  )
}

function Row({ e, onOpen }: { e: SignalEvaluation; onOpen: (item: DrawerItem) => void }) {
  const [open, setOpen] = useState(false)
  const s = STATUS[e.status] ?? STATUS.gated
  const stale = e.updated_at ? Date.now() - new Date(e.updated_at).getTime() > 5 * 60 * 1000 : false
  return (
    <div style={{ borderBottom: "1px solid var(--border)", opacity: stale ? 0.5 : 1 }}>
      <div
        onClick={() => e.detail && setOpen(o => !o)}
        style={{
          display: "grid", gridTemplateColumns: "120px 110px 110px 90px 1fr", gap: "1rem",
          alignItems: "center", padding: "0.6rem 0.85rem", cursor: e.detail ? "pointer" : "default",
        }}
      >
        <button
          onClick={ev => { ev.stopPropagation(); onOpen({ kind: "instrument", data: { instrument: e.instrument } }) }}
          style={{
            fontWeight: 700, fontSize: "0.8rem",
            background: "none", border: "none", color: "inherit", cursor: "pointer",
            padding: 0, fontFamily: "inherit", textAlign: "left",
            textDecoration: "underline", textDecorationColor: "var(--border-hi)",
            textUnderlineOffset: "3px",
          }}
        >
          {e.instrument}
        </button>
        <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>{e.regime ?? "—"}</span>
        <span style={{ fontSize: "0.62rem", fontWeight: 700, letterSpacing: "0.06em", color: s.color }}>
          {s.label}
        </span>
        <Bar value={e.setup_distance} />
        <span style={{
          fontSize: "0.65rem", color: "var(--dim)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {e.reason ?? ""}
        </span>
      </div>
      {open && e.detail && (
        <div style={{
          display: "flex", flexWrap: "wrap", gap: "0.5rem 1.25rem",
          padding: "0.4rem 0.85rem 0.7rem", fontSize: "0.6rem", color: "var(--muted)",
        }}>
          {Object.entries(e.detail).map(([k, v]) => (
            <span key={k}>
              {k}:{" "}
              <span style={{ color: v === true ? "var(--green)" : v === false ? "var(--red)" : "var(--sub)" }}>
                {String(v)}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Insight() {
  const [rows,       setRows]       = useState<SignalEvaluation[]>([])
  const [drawerItem, setDrawerItem] = useState<DrawerItem | null>(null)

  const load = useCallback(() =>
    supabase.from("signal_evaluations").select("*").order("instrument")
      .then(({ data }) => data && setRows(data as SignalEvaluation[])), [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30_000)
    const ch = supabase.channel("insight-rt")
      .on("postgres_changes", { event: "*", schema: "public", table: "signal_evaluations" }, load)
      .subscribe()
    return () => { supabase.removeChannel(ch); clearInterval(timer) }
  }, [load])

  const latest = rows.reduce<string | null>((a, r) => !a || r.updated_at > a ? r.updated_at : a, null)

  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "1rem", marginBottom: "0.75rem" }}>
        <h1 style={{ fontSize: "0.85rem", letterSpacing: "0.1em", color: "var(--text)" }}>WHY NO SIGNAL</h1>
        {latest && <span style={{ fontSize: "0.6rem", color: "var(--dim)" }}>updated {timeAgo(latest)} ago</span>}
      </div>
      <div style={{ background: "var(--panel)", border: "1px solid var(--border)" }}>
        {rows.map(e => <Row key={e.instrument} e={e} onOpen={setDrawerItem} />)}
        {rows.length === 0 && (
          <div style={{ padding: "2rem", textAlign: "center", color: "var(--muted)", fontSize: "0.72rem" }}>
            — no evaluations yet —
          </div>
        )}
      </div>
      <InstrumentDrawer item={drawerItem} onClose={() => setDrawerItem(null)} />
    </div>
  )
}
