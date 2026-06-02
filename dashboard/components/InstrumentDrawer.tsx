"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import type { Position, Signal, SignalEvaluation } from "@/lib/types"
import { fmtPrice, fmtPips, fmtPnl, fmtPct, timeAgo } from "@/lib/fmt"
import { TradingViewChart, tvSymbol } from "./TradingViewChart"

export type DrawerItem =
  | { kind: "position"; data: Position }
  | { kind: "signal";   data: Signal   }

function proximity(pos: Position): number {
  if (!pos.stop_loss || !pos.take_profit || !pos.current_price) return 0.5
  const sl = pos.stop_loss, tp = pos.take_profit, cur = pos.current_price
  const isBuy = pos.direction === "BUY"
  const range = isBuy ? tp - sl : sl - tp
  if (range <= 0) return 0.5
  return Math.max(0, Math.min(1, isBuy ? (cur - sl) / range : (sl - cur) / range))
}

function DetailRow({ label, value, color }: {
  label: string
  value: React.ReactNode
  color?: string
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
      padding: "0.38rem 0", borderBottom: "1px solid var(--border)" }}>
      <span style={{ fontSize: "0.52rem", letterSpacing: "0.12em", color: "var(--muted)" }}>
        {label}
      </span>
      <span style={{ fontSize: "0.72rem", fontVariantNumeric: "tabular-nums", color: color ?? "var(--text)" }}>
        {value}
      </span>
    </div>
  )
}

function SectionHead({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", margin: "1rem 0 0.5rem" }}>
      <span style={{ fontSize: "0.5rem", letterSpacing: "0.18em", color: "var(--accent)" }}>
        {children}
      </span>
      <div style={{ flex: 1, height: 1, background: "linear-gradient(to right, var(--border-hi), transparent)" }} />
    </div>
  )
}

function PositionDetails({ pos }: { pos: Position }) {
  const prox  = proximity(pos)
  const pnl   = pos.profit ?? 0
  const rr    = pos.stop_loss && pos.take_profit
    ? Math.abs(pos.take_profit - pos.entry_price) / Math.abs(pos.entry_price - pos.stop_loss)
    : null
  const cur   = pos.current_price ?? pos.entry_price
  const curGreen = pos.direction === "BUY" ? cur >= pos.entry_price : cur <= pos.entry_price

  const slPips = pos.stop_loss
    ? fmtPips(Math.abs(cur - pos.stop_loss), pos.instrument) : null
  const tpPips = pos.take_profit
    ? fmtPips(Math.abs(pos.take_profit - cur), pos.instrument) : null

  const isBuy  = pos.direction === "BUY"
  const sl = pos.stop_loss, tp = pos.take_profit
  const range  = sl && tp ? (isBuy ? tp - sl : sl - tp) : 0
  const entryPct   = sl && tp && range > 0
    ? Math.max(0, Math.min(1, isBuy ? (pos.entry_price - sl) / range : (sl - pos.entry_price) / range))
    : 0.5
  const currentPct = sl && tp && range > 0
    ? Math.max(0, Math.min(1, isBuy ? (cur - sl) / range : (sl - cur) / range))
    : 0.5
  const fillColor = currentPct < 0.15 ? "var(--red)"
                  : currentPct <= entryPct ? "var(--yellow)"
                  : "var(--green)"

  return (
    <>
      <SectionHead>POSITION</SectionHead>

      {sl && tp && (
        <div style={{ marginBottom: "0.75rem" }}>
          <div style={{ position: "relative", height: 6, background: "var(--border-hi)", borderRadius: 1 }}>
            <div style={{
              position: "absolute", left: 0, height: "100%",
              width: `${currentPct * 100}%`, background: fillColor,
              opacity: 0.45, borderRadius: 1,
              transition: "width 0.6s cubic-bezier(0.16,1,0.3,1)",
            }} />
            <div style={{
              position: "absolute", top: -2, height: 10, width: 1,
              background: "var(--sub)", left: `${entryPct * 100}%`,
            }} />
            <div style={{
              position: "absolute", top: -4, height: 14, width: 2,
              background: fillColor, left: `${currentPct * 100}%`,
              transform: "translateX(-1px)",
              boxShadow: `0 0 6px ${fillColor}`,
              transition: "left 0.6s cubic-bezier(0.16,1,0.3,1)",
            }} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.35rem", fontSize: "0.55rem" }}>
            <span style={{ color: "var(--red)" }}>SL {fmtPrice(sl, pos.instrument)}</span>
            <span style={{ color: "var(--muted)" }}>entry {fmtPrice(pos.entry_price, pos.instrument)}</span>
            <span style={{ color: "var(--teal)" }}>TP {fmtPrice(tp, pos.instrument)}</span>
          </div>
        </div>
      )}

      <DetailRow label="P&L"
        value={`${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)} USD`}
        color={pnl >= 0 ? "var(--green)" : "var(--red)"} />
      <DetailRow label="CURRENT"
        value={fmtPrice(cur, pos.instrument)}
        color={curGreen ? "var(--green)" : "var(--red)"} />
      <DetailRow label="ENTRY"   value={fmtPrice(pos.entry_price, pos.instrument)} />
      {sl && <DetailRow label="STOP LOSS"
        value={`${fmtPrice(sl, pos.instrument)}${slPips ? `  (${slPips}p)` : ""}`}
        color="var(--red)" />}
      {tp && <DetailRow label="TAKE PROFIT"
        value={`${fmtPrice(tp, pos.instrument)}${tpPips ? `  (${tpPips}p)` : ""}`}
        color="var(--teal)" />}
      {rr != null && (
        <DetailRow label="R/R RATIO"
          value={`${rr.toFixed(2)} : 1`}
          color={rr >= 2 ? "var(--accent)" : rr >= 1.5 ? "var(--sub)" : "var(--muted)"} />
      )}
      <DetailRow label="VOLUME"   value={`${pos.volume} lots`} />
      <DetailRow label="PROXIMITY TO SL"
        value={`${(prox * 100).toFixed(0)}%`}
        color={prox < 0.18 ? "var(--red)" : prox > 0.7 ? "var(--green)" : "var(--muted)"} />
      {pos.strategy && <DetailRow label="STRATEGY" value={pos.strategy} />}
      {pos.regime   && <DetailRow label="REGIME"   value={pos.regime.replace("_", " ")} />}
      <DetailRow label="OPENED"  value={timeAgo(pos.opened_at) + " ago"} />
      <DetailRow label="TICKET"  value={`#${pos.ticket}`} color="var(--muted)" />
    </>
  )
}

function SignalDetails({ sig }: { sig: Signal }) {
  const isApprove = sig.ai_decision === "APPROVE"
  const isVeto    = sig.ai_decision === "VETO"
  return (
    <>
      <SectionHead>SIGNAL</SectionHead>
      {sig.confidence != null && (
        <div style={{ marginBottom: "0.6rem" }}>
          <div style={{ fontSize: "0.5rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.25rem" }}>
            CONFIDENCE
          </div>
          <div style={{ display: "flex", gap: "1.5px" }}>
            {[...Array(10)].map((_, i) => (
              <div key={i} style={{
                flex: 1, height: 4,
                background: i / 10 < (sig.confidence ?? 0) ? "var(--accent)" : "var(--border-hi)",
                opacity: i / 10 < (sig.confidence ?? 0) ? (0.4 + (i / 10) * 0.6) : 0.25,
              }} />
            ))}
          </div>
          <div style={{ fontSize: "0.6rem", color: "var(--accent)", marginTop: "0.2rem" }}>
            {((sig.confidence ?? 0) * 100).toFixed(0)}%
          </div>
        </div>
      )}
      {sig.regime && (
        <DetailRow label="REGIME" value={sig.regime.replace("_", " ")} />
      )}
      {sig.strategy && <DetailRow label="STRATEGY" value={sig.strategy} />}
      {sig.ai_decision && (
        <DetailRow label="AI DECISION"
          value={`${isApprove ? "✓" : isVeto ? "✗" : "↻"} ${sig.ai_decision}`}
          color={isApprove ? "var(--green)" : isVeto ? "var(--red)" : "var(--yellow)"} />
      )}
      {sig.ai_reasoning && (
        <div style={{ marginTop: "0.5rem" }}>
          <div style={{ fontSize: "0.5rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.2rem" }}>
            AI REASONING
          </div>
          <div style={{ fontSize: "0.62rem", color: "var(--sub)", lineHeight: 1.55 }}>
            {sig.ai_reasoning}
          </div>
        </div>
      )}
      {sig.rejection_reason && (
        <div style={{ marginTop: "0.5rem" }}>
          <div style={{ fontSize: "0.5rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.2rem" }}>
            REJECTION REASON
          </div>
          <div style={{ fontSize: "0.62rem", color: "var(--yellow)", lineHeight: 1.55 }}>
            {sig.rejection_reason}
          </div>
        </div>
      )}
      <DetailRow label="TIME" value={timeAgo(sig.created_at) + " ago"} color="var(--muted)" />
    </>
  )
}

const EVAL_STATUS: Record<string, { color: string; label: string }> = {
  signal:   { color: "var(--green)",  label: "SETUP READY" },
  no_setup: { color: "var(--yellow)", label: "NO SETUP"    },
  gated:    { color: "var(--muted)",  label: "GATED"       },
}

function SetupStatus({ ev }: { ev: SignalEvaluation }) {
  const s    = EVAL_STATUS[ev.status] ?? EVAL_STATUS.gated
  const dist = ev.setup_distance ?? 0

  return (
    <>
      <SectionHead>SETUP STATUS</SectionHead>

      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.6rem" }}>
        <span style={{
          fontSize: "0.58rem", fontWeight: 700, letterSpacing: "0.08em",
          color: s.color, padding: "0.12rem 0.45rem",
          border: `1px solid ${s.color}`, opacity: 0.9,
        }}>{s.label}</span>
        {ev.in_session === false && (
          <span style={{ fontSize: "0.52rem", color: "var(--muted)", letterSpacing: "0.06em" }}>
            OUT OF SESSION
          </span>
        )}
      </div>

      <div style={{ marginBottom: "0.6rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.5rem",
          color: "var(--muted)", marginBottom: "0.22rem" }}>
          <span>DISTANCE TO TRIGGER</span>
          <span style={{ color: s.color }}>{(dist * 100).toFixed(0)}%</span>
        </div>
        <div style={{ display: "flex", gap: "1.5px" }}>
          {[...Array(10)].map((_, i) => (
            <div key={i} style={{
              flex: 1, height: 4,
              background: i / 10 < dist ? s.color : "var(--border-hi)",
              opacity: i / 10 < dist ? (0.35 + (i / 10) * 0.65) : 0.25,
              transition: "background 0.3s",
            }} />
          ))}
        </div>
      </div>

      {ev.reason && (
        <div style={{ marginBottom: "0.6rem" }}>
          <div style={{ fontSize: "0.5rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.2rem" }}>
            REASON
          </div>
          <div style={{ fontSize: "0.62rem", color: "var(--sub)", lineHeight: 1.55 }}>
            {ev.reason}
          </div>
        </div>
      )}

      {ev.detail && Object.keys(ev.detail).length > 0 && (
        <div>
          <div style={{ fontSize: "0.5rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.35rem" }}>
            BOT DETAIL
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {Object.entries(ev.detail).map(([k, v]) => (
              <DetailRow
                key={k}
                label={k.replace(/_/g, " ").toUpperCase()}
                value={String(v)}
                color={v === true ? "var(--green)" : v === false ? "var(--red)" : "var(--sub)"}
              />
            ))}
          </div>
        </div>
      )}
    </>
  )
}

export function InstrumentDrawer({
  item,
  onClose,
}: {
  item: DrawerItem | null
  onClose: () => void
}) {
  const [evalData, setEvalData] = useState<SignalEvaluation | null | undefined>(undefined)

  useEffect(() => {
    if (!item) { setEvalData(undefined); return }
    setEvalData(undefined)
    const inst = item.data.instrument
    supabase.from("signal_evaluations").select("*").eq("instrument", inst).single()
      .then(({ data }) => setEvalData(data as SignalEvaluation | null))
  }, [item])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  if (!item) return null

  const instrument = item.data.instrument
  const sym        = tvSymbol(instrument)
  const isBuy      = item.data.direction === "BUY"
  const dirColor   = isBuy ? "var(--green)" : "var(--red)"

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed", inset: 0,
          background: "rgba(0,0,0,0.45)",
          zIndex: 40,
        }}
      />

      <div className="drawerIn" style={{
        position: "fixed", top: 0, right: 0,
        width: 440, height: "100vh",
        background: "var(--surface)",
        borderLeft: "1px solid var(--border)",
        zIndex: 50,
        display: "flex", flexDirection: "column",
        overflow: "hidden",
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: "0.65rem",
          padding: "0.9rem 1.1rem",
          borderBottom: "1px solid var(--border)",
          flexShrink: 0,
        }}>
          <span style={{ fontSize: "1.05rem", fontWeight: 700, letterSpacing: "0.03em" }}>
            {instrument}
          </span>
          <span style={{
            fontSize: "0.57rem", fontWeight: 700, padding: "0.1rem 0.42rem",
            background: isBuy ? "rgba(0,200,122,0.1)" : "rgba(232,64,64,0.1)",
            color: dirColor, letterSpacing: "0.08em",
            borderLeft: `2px solid ${dirColor}`,
          }}>
            {item.data.direction}
          </span>
          <span style={{ fontSize: "0.52rem", letterSpacing: "0.1em", color: "var(--muted)" }}>
            {item.kind === "position" ? "POSITION" : "SIGNAL"}
          </span>
          <button
            onClick={onClose}
            style={{
              marginLeft: "auto", background: "none", border: "none",
              color: "var(--muted)", fontSize: "1rem", cursor: "pointer",
              padding: "0.1rem 0.3rem", lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "0 1.1rem 1.5rem" }}>
          <div style={{ margin: "0.75rem -1.1rem 0", borderBottom: "1px solid var(--border)" }}>
            <TradingViewChart key={sym} symbol={sym} />
          </div>

          {item.kind === "position" && <PositionDetails pos={item.data} />}
          {item.kind === "signal"   && <SignalDetails   sig={item.data} />}

          {evalData != null && <SetupStatus ev={evalData} />}
          {evalData === null && (
            <div style={{ marginTop: "1rem", fontSize: "0.6rem", color: "var(--muted)" }}>
              — no setup data for {instrument} —
            </div>
          )}
        </div>
      </div>
    </>
  )
}
