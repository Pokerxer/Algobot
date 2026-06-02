"use client"
import { useEffect, useRef, useState, useCallback, type ReactNode } from "react"
import { supabase } from "@/lib/supabase"
import type { BotStatus, Position, RegimeSnapshot, Signal, Trade } from "@/lib/types"
import { fmtPrice, fmtPnl, fmtPips, fmtPct, timeAgo } from "@/lib/fmt"
import { InstrumentDrawer, type DrawerItem } from "@/components/InstrumentDrawer"

const MAX_HOLDING_HOURS = 24
const MAX_DRAWDOWN_PCT  = 0.05

/* ── animated number hook ───────────────────────────────────── */
function useAnimatedValue(target: number, duration = 500): number {
  const [value, setValue] = useState(target)
  const frame  = useRef<number>(0)
  const start  = useRef({ from: target, to: target, t0: 0 })

  useEffect(() => {
    if (target === start.current.to) return
    start.current = { from: value, to: target, t0: performance.now() }
    const tick = (now: number) => {
      const p = Math.min((now - start.current.t0) / duration, 1)
      const e = 1 - Math.pow(1 - p, 3)
      setValue(start.current.from + (start.current.to - start.current.from) * e)
      if (p < 1) frame.current = requestAnimationFrame(tick)
    }
    cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame.current)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])

  return value
}

/* ── helpers ────────────────────────────────────────────────── */
function agePct(openedAt: string): number {
  return Math.min((Date.now() - new Date(openedAt).getTime()) / (MAX_HOLDING_HOURS * 3_600_000), 1)
}

function proximity(pos: Position): number {
  if (!pos.stop_loss || !pos.take_profit || !pos.current_price) return 0.5
  const sl = pos.stop_loss, tp = pos.take_profit, cur = pos.current_price
  const isBuy = pos.direction === "BUY"
  const range = isBuy ? tp - sl : sl - tp
  if (range <= 0) return 0.5
  return Math.max(0, Math.min(1, isBuy ? (cur - sl) / range : (sl - cur) / range))
}

function fmtUptime(seconds: number | null): string {
  if (!seconds) return "—"
  if (seconds < 60)   return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

/* ── SECTION LABEL ──────────────────────────────────────────── */
function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.65rem", marginBottom: "0.65rem" }}>
      <span style={{
        fontSize: "0.52rem", letterSpacing: "0.18em",
        color: "var(--accent)", fontWeight: 500, whiteSpace: "nowrap",
      }}>
        {children}
      </span>
      <div style={{
        flex: 1, height: "1px",
        background: "linear-gradient(to right, var(--border-hi), transparent)",
      }} />
      {right && (
        <span style={{ fontSize: "0.52rem", color: "var(--muted)", whiteSpace: "nowrap" }}>
          {right}
        </span>
      )}
    </div>
  )
}

/* ── METRIC BLOCK ───────────────────────────────────────────── */
function Metric({ label, value, sub, color }: {
  label: string; value: ReactNode; sub?: ReactNode; color?: string
}) {
  return (
    <div>
      <div style={{ fontSize: "0.5rem", letterSpacing: "0.14em", color: "var(--muted)", marginBottom: "0.18rem" }}>
        {label}
      </div>
      <div style={{
        fontSize: "1.05rem", fontWeight: 700, fontVariantNumeric: "tabular-nums",
        color: color ?? "var(--text)", lineHeight: 1.1,
      }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: "0.52rem", color: "var(--muted)", marginTop: "0.12rem" }}>{sub}</div>
      )}
    </div>
  )
}

/* ── PRICE RANGE BAR ────────────────────────────────────────── */
function PriceRangeBar({ pos }: { pos: Position }) {
  const { stop_loss: sl, take_profit: tp, entry_price: entry,
          current_price: cur, direction, instrument } = pos
  if (!sl || !tp) return null
  const isBuy   = direction === "BUY"
  const current = cur ?? entry
  const range   = isBuy ? tp - sl : sl - tp
  if (range <= 0) return null

  const entryPct   = Math.max(0, Math.min(1, isBuy ? (entry   - sl) / range : (sl - entry  ) / range))
  const currentPct = Math.max(0, Math.min(1, isBuy ? (current - sl) / range : (sl - current) / range))
  const inProfit   = currentPct > entryPct

  const fillColor = currentPct < 0.15 ? "var(--red)"
                  : !inProfit          ? "var(--yellow)"
                  : "var(--green)"

  const slPips = fmtPips(Math.abs(current - sl), instrument)
  const tpPips = fmtPips(Math.abs(tp - current), instrument)

  return (
    <div style={{ margin: "0.85rem 0 0.5rem" }}>
      <div style={{ position: "relative", height: 5, background: "var(--border-hi)", borderRadius: 1 }}>
        {/* fill */}
        <div style={{
          position: "absolute", left: 0, height: "100%",
          width: `${currentPct * 100}%`,
          background: fillColor, opacity: 0.45, borderRadius: 1,
          transition: "width 0.7s cubic-bezier(0.16,1,0.3,1)",
        }} />
        {/* entry marker */}
        <div style={{
          position: "absolute", left: `${entryPct * 100}%`,
          top: -2, height: 9, width: 1,
          background: "var(--sub)", transform: "translateX(-0.5px)",
        }} />
        {/* current-price tick */}
        <div style={{
          position: "absolute", left: `${currentPct * 100}%`,
          top: -4, height: 13, width: 2,
          background: fillColor, transform: "translateX(-1px)",
          boxShadow: `0 0 6px ${fillColor}`,
          transition: "left 0.7s cubic-bezier(0.16,1,0.3,1), background 0.4s",
        }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.38rem", fontSize: "0.57rem" }}>
        <span style={{ color: "var(--red)" }}>
          SL {fmtPrice(sl, instrument)}
          <span style={{ color: "var(--muted)", marginLeft: "0.3rem" }}>←{slPips}p</span>
        </span>
        <span style={{ color: "var(--muted)", fontSize: "0.52rem" }}>
          entry {fmtPrice(entry, instrument)}
        </span>
        <span style={{ color: "var(--teal)" }}>
          <span style={{ color: "var(--muted)", marginRight: "0.3rem" }}>{tpPips}p→</span>
          TP {fmtPrice(tp, instrument)}
        </span>
      </div>
    </div>
  )
}

/* ── POSITION CARD ──────────────────────────────────────────── */
function PositionCard({ pos, index, onOpen }: {
  pos: Position
  index: number
  onOpen: (item: DrawerItem) => void
}) {
  const rawPnl  = pos.profit ?? 0
  const animPnl = useAnimatedValue(rawPnl, 600)
  const prox    = proximity(pos)
  const age     = agePct(pos.opened_at)
  const danger  = prox < 0.18
  const rr      = pos.stop_loss && pos.take_profit
    ? Math.abs(pos.take_profit - pos.entry_price) / Math.abs(pos.entry_price - pos.stop_loss)
    : null

  const cur      = pos.current_price ?? pos.entry_price
  const curGreen = pos.direction === "BUY" ? cur >= pos.entry_price : cur <= pos.entry_price

  // Left stripe: thick colored border communicates P&L state instantly
  const stripeColor = danger            ? "var(--red)"
                    : rawPnl > 0        ? "var(--green)"
                    : rawPnl < 0        ? "rgba(232,64,64,0.55)"
                    : "var(--border-hi)"

  return (
    <div className="cardIn" style={{
      background: "var(--panel)",
      borderTop: "1px solid var(--border)",
      borderRight: "1px solid var(--border)",
      borderBottom: "1px solid var(--border)",
      borderLeft: `3px solid ${stripeColor}`,
      padding: "0.95rem 1.1rem",
      position: "relative", overflow: "hidden",
      animationDelay: `${index * 0.08}s`,
      animation: danger
        ? `cardIn 0.35s cubic-bezier(0.16,1,0.3,1) ${index * 0.08}s both, dangerFlash 1.4s ease-in-out infinite`
        : undefined,
      transition: "border-left-color 0.4s",
    }}>
      {/* Corner triangle — profit/loss indicator */}
      <div style={{
        position: "absolute", top: 0, right: 0,
        width: 0, height: 0, borderStyle: "solid",
        borderWidth: "0 18px 18px 0",
        borderColor: `transparent ${
          rawPnl > 0 ? "rgba(0,200,122,0.18)" : rawPnl < 0 ? "rgba(232,64,64,0.14)" : "transparent"
        } transparent transparent`,
      }} />

      {/* Subtle radial glow */}
      {(rawPnl > 0 || rawPnl < 0) && (
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          background: rawPnl > 0
            ? "radial-gradient(ellipse at 100% 0%, rgba(0,200,122,0.04) 0%, transparent 65%)"
            : "radial-gradient(ellipse at 100% 0%, rgba(232,64,64,0.04) 0%, transparent 65%)",
        }} />
      )}

      {/* Header: instrument + direction + PnL */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <button
            onClick={() => onOpen({ kind: "position", data: pos })}
            style={{
              fontSize: "0.95rem", fontWeight: 700, letterSpacing: "0.03em",
              background: "none", border: "none", color: "inherit", cursor: "pointer",
              padding: 0, fontFamily: "inherit",
              textDecoration: "underline", textDecorationColor: "var(--border-hi)",
              textUnderlineOffset: "3px",
            }}
          >
            {pos.instrument}
          </button>
          <span style={{
            fontSize: "0.57rem", fontWeight: 700, padding: "0.1rem 0.42rem",
            background: pos.direction === "BUY" ? "rgba(0,200,122,0.1)" : "rgba(232,64,64,0.1)",
            color: pos.direction === "BUY" ? "var(--green)" : "var(--red)",
            letterSpacing: "0.08em",
            borderLeft: `2px solid ${pos.direction === "BUY" ? "rgba(0,200,122,0.45)" : "rgba(232,64,64,0.45)"}`,
          }}>
            {pos.direction}
          </span>
          <span style={{ fontSize: "0.6rem", color: "var(--muted)" }}>{pos.volume}L</span>
          {danger && (
            <span style={{
              fontSize: "0.52rem", letterSpacing: "0.1em", color: "var(--red)",
              animation: "pulseUrgent 0.9s ease-in-out infinite",
            }}>⚠ SL</span>
          )}
        </div>
        <div style={{
          fontSize: "1.1rem", fontWeight: 700, fontVariantNumeric: "tabular-nums",
          color: animPnl >= 0 ? "var(--green)" : "var(--red)",
          transition: "color 0.4s",
        }}>
          {animPnl >= 0 ? "+" : ""}{animPnl.toFixed(2)}
          <span style={{ fontSize: "0.52rem", fontWeight: 400, color: "var(--muted)", marginLeft: "0.2rem" }}>$</span>
        </div>
      </div>

      {/* Prices */}
      <div style={{ display: "flex", gap: "2rem", marginTop: "0.65rem", alignItems: "flex-end" }}>
        <div>
          <div style={{ fontSize: "0.49rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.12rem" }}>ENTRY</div>
          <div style={{ fontSize: "0.82rem", fontVariantNumeric: "tabular-nums", color: "var(--sub)" }}>
            {fmtPrice(pos.entry_price, pos.instrument)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: "0.49rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.12rem" }}>CURRENT</div>
          <div style={{
            fontSize: "0.82rem", fontWeight: 600, fontVariantNumeric: "tabular-nums",
            color: curGreen ? "var(--green)" : "var(--red)",
            transition: "color 0.4s",
          }}>
            {fmtPrice(pos.current_price, pos.instrument)}
          </div>
        </div>
        {rr != null && (
          <div style={{ marginLeft: "auto" }}>
            <div style={{ fontSize: "0.49rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.12rem" }}>R/R</div>
            <div style={{
              fontSize: "0.78rem", fontVariantNumeric: "tabular-nums",
              color: rr >= 2 ? "var(--accent)" : rr >= 1.5 ? "var(--sub)" : "var(--muted)",
            }}>{rr.toFixed(2)}:1</div>
          </div>
        )}
      </div>

      {/* Price bar */}
      <PriceRangeBar pos={pos} />

      {/* Footer: age bar + meta */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.85rem", marginTop: "0.6rem" }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.49rem", marginBottom: "0.2rem" }}>
            <span style={{ color: "var(--muted)" }}>{timeAgo(pos.opened_at)}</span>
            <span style={{ color: age > 0.85 ? "var(--red)" : "var(--muted)" }}>
              {(age * 100).toFixed(0)}% / {MAX_HOLDING_HOURS}h
            </span>
          </div>
          <div style={{ height: 2, background: "var(--border)" }}>
            <div style={{
              width: `${age * 100}%`, height: "100%",
              background: age > 0.85 ? "var(--red)" : age > 0.6 ? "var(--yellow)" : "var(--border-hi)",
              transition: "width 0.5s",
            }} />
          </div>
        </div>
        <div style={{ fontSize: "0.55rem", color: "var(--muted)", whiteSpace: "nowrap", textAlign: "right" }}>
          {pos.strategy ?? ""}
          <span style={{ fontSize: "0.48rem", color: "var(--dim)", marginLeft: "0.35rem" }}>#{pos.ticket}</span>
        </div>
      </div>
    </div>
  )
}

/* ── REGIME TILE ────────────────────────────────────────────── */
function RegimeTile({ r }: { r: RegimeSnapshot }) {
  const isTrendUp   = r.regime === "TRENDING_UP"
  const isTrendDown = r.regime === "TRENDING_DOWN"
  const isRanging   = r.regime === "RANGING"

  const color = isTrendUp   ? "var(--green)"
              : isTrendDown ? "var(--red)"
              : isRanging   ? "var(--accent)"
              : "var(--muted)"

  const icon  = isTrendUp ? "↑" : isTrendDown ? "↓" : isRanging ? "⇔" : "~"
  const label = isTrendUp ? "TREND" : isTrendDown ? "TREND" : isRanging ? "RANGE" : "CHOPPY"

  const conf    = r.confidence ?? 0
  const staleMs = r.recorded_at ? Date.now() - new Date(r.recorded_at).getTime() : 0
  const isStale = staleMs > 5 * 60 * 1000
  const tileColor = isStale ? "var(--muted)" : color

  return (
    <div style={{
      background: "var(--panel)",
      border: "1px solid var(--border)",
      padding: "0.7rem 0.9rem",
      minWidth: 112,
      opacity: isStale ? 0.45 : 1,
      transition: "opacity 0.4s",
      position: "relative",
      overflow: "hidden",
    }}>
      {/* Top band — colored by regime */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: 2,
        background: tileColor,
        opacity: isStale ? 0.25 : Math.max(0.2, conf * 0.8 + 0.2),
        transition: "opacity 0.4s",
      }} />

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.3rem" }}>
        <div style={{ fontSize: "0.68rem", fontWeight: 700, letterSpacing: "0.04em" }}>
          {r.instrument}
        </div>
        {isStale
          ? <span style={{ fontSize: "0.47rem", color: "var(--muted)", letterSpacing: "0.07em" }}>STALE</span>
          : <span style={{ fontSize: "0.9rem", color: tileColor, lineHeight: 1 }}>{icon}</span>
        }
      </div>

      <div style={{ fontSize: "0.57rem", color: tileColor, letterSpacing: "0.07em", fontWeight: 600, marginBottom: "0.42rem" }}>
        {label}
      </div>

      {/* Segmented confidence bar */}
      <div style={{ display: "flex", gap: "1.5px", marginBottom: "0.32rem" }}>
        {[...Array(10)].map((_, i) => (
          <div key={i} style={{
            flex: 1, height: 3,
            background: i / 10 < conf ? tileColor : "var(--border-hi)",
            opacity: i / 10 < conf ? (0.35 + (i / 10) * 0.65) : 0.25,
            transition: "background 0.4s",
          }} />
        ))}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.5rem", color: "var(--muted)" }}>
        {r.adx != null && <span>ADX {r.adx.toFixed(1)}</span>}
        <span style={{ marginLeft: "auto", color: conf < 0.01 ? "var(--dim)" : "var(--muted)" }}>
          {conf < 0.01 ? "—" : fmtPct(conf)}
        </span>
      </div>
      {r.recorded_at && (
        <div style={{ fontSize: "0.47rem", color: "var(--dim)", marginTop: "0.2rem" }}>
          {timeAgo(r.recorded_at)}
        </div>
      )}
    </div>
  )
}

/* ── SIGNAL ROW ─────────────────────────────────────────────── */
function SignalRow({ s, i, isNew, onOpen }: {
  s: Signal
  i: number
  isNew: boolean
  onOpen: (item: DrawerItem) => void
}) {
  const isVeto    = s.ai_decision === "VETO"
  const isApprove = s.ai_decision === "APPROVE"
  const isBuy     = s.direction === "BUY"

  return (
    <div className={isNew ? "slideFromTop" : "fadein"} style={{
      padding: "0.55rem 0.85rem",
      borderTop: i === 0 ? "none" : "1px solid var(--border)",
      display: "grid",
      gridTemplateColumns: "auto 1fr auto",
      gap: "0.55rem",
      alignItems: "start",
      animationDelay: isNew ? "0s" : `${i * 0.025}s`,
      opacity: isVeto ? 0.6 : 1,
    }}>
      {/* Direction pill */}
      <div style={{
        padding: "0.1rem 0.38rem",
        background: isBuy ? "rgba(0,200,122,0.09)" : "rgba(232,64,64,0.09)",
        color: isBuy ? "var(--green)" : "var(--red)",
        fontSize: "0.53rem", fontWeight: 700, letterSpacing: "0.08em",
        alignSelf: "center",
        borderTop: `1px solid ${isBuy ? "rgba(0,200,122,0.3)" : "rgba(232,64,64,0.3)"}`,
      }}>
        {s.direction}
      </div>

      {/* Content */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.1rem" }}>
          <button
            onClick={() => onOpen({ kind: "signal", data: s })}
            style={{
              fontSize: "0.72rem", fontWeight: 600,
              background: "none", border: "none", color: "inherit", cursor: "pointer",
              padding: 0, fontFamily: "inherit",
              textDecoration: "underline", textDecorationColor: "var(--border-hi)",
              textUnderlineOffset: "3px",
            }}
          >
            {s.instrument}
          </button>
          {s.executed && (
            <span style={{
              fontSize: "0.49rem", letterSpacing: "0.08em", color: "var(--teal)",
              borderBottom: "1px solid rgba(0,200,190,0.3)",
            }}>EXEC</span>
          )}
          {s.confidence != null && (
            <span style={{ fontSize: "0.57rem", color: "var(--muted)" }}>
              {(s.confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>
        <div style={{ fontSize: "0.57rem", color: "var(--muted)", display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {s.strategy && <span>{s.strategy}</span>}
          {s.ai_decision && (
            <span style={{ color: isApprove ? "var(--green)" : isVeto ? "var(--red)" : "var(--yellow)", fontSize: "0.53rem" }}>
              {isApprove ? "✓" : isVeto ? "✗" : "↻"} {s.ai_decision}
            </span>
          )}
        </div>
        {s.ai_reasoning && (
          <div style={{
            fontSize: "0.53rem", color: "var(--dim)", marginTop: "0.1rem",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            maxWidth: 220,
          }}>
            {s.ai_reasoning}
          </div>
        )}
      </div>

      {/* Timestamp */}
      <div style={{ fontSize: "0.5rem", color: "var(--muted)", textAlign: "right", alignSelf: "center" }}>
        {timeAgo(s.created_at)}
      </div>
    </div>
  )
}

/* ── DRAWDOWN GAUGE — segmented LED bar ─────────────────────── */
function DrawdownGauge({ used, balance }: { used: number; balance: number }) {
  const limit = balance * MAX_DRAWDOWN_PCT
  const pct   = limit > 0 ? Math.min(Math.abs(used) / limit, 1) : 0
  const color = pct > 0.75 ? "var(--red)" : pct > 0.4 ? "var(--yellow)" : "var(--green)"
  const segs  = 8
  const filled = Math.round(pct * segs)

  return (
    <div>
      <div style={{ fontSize: "0.5rem", letterSpacing: "0.14em", color: "var(--muted)", marginBottom: "0.28rem" }}>
        DRAWDOWN
      </div>
      <div style={{ display: "flex", gap: "2px" }}>
        {[...Array(segs)].map((_, i) => (
          <div key={i} style={{
            width: 7, height: 14,
            background: i < filled ? color : "var(--border-hi)",
            opacity: i < filled ? (0.4 + (i / segs) * 0.6) : 0.25,
            transition: "background 0.4s, opacity 0.4s",
          }} />
        ))}
      </div>
      <div style={{ fontSize: "0.5rem", color, marginTop: "0.18rem", fontVariantNumeric: "tabular-nums" }}>
        {(pct * 100).toFixed(0)}%
        <span style={{ color: "var(--dim)", marginLeft: "0.25rem" }}>/ ${limit.toFixed(0)}</span>
      </div>
    </div>
  )
}

/* ── PAGE ───────────────────────────────────────────────────── */
export default function Overview() {
  const [botStatus,   setBotStatus]   = useState<BotStatus | null>(null)
  const [positions,   setPositions]   = useState<Position[]>([])
  const [regimes,     setRegimes]     = useState<RegimeSnapshot[]>([])
  const [signals,     setSignals]     = useState<Signal[]>([])
  const [todayTrades, setTodayTrades] = useState<Trade[]>([])
  const [, setTick]                   = useState(0)
  const [drawerItem, setDrawerItem] = useState<DrawerItem | null>(null)

  const prevSignalIds = useRef<Set<number>>(new Set())

  const loadPositions = useCallback(() =>
    supabase.from("positions").select("*").order("opened_at", { ascending: false })
      .then(({ data }) => data && setPositions(data as Position[])), [])

  const loadSignals = useCallback(() =>
    supabase.from("signals").select("*").order("created_at", { ascending: false }).limit(15)
      .then(({ data }) => {
        if (!data) return
        setSignals(prev => {
          const next = data as Signal[]
          prevSignalIds.current = new Set(prev.map(s => s.id))
          return next
        })
      }), [])

  const loadRegimes = useCallback(() =>
    supabase.from("regime_snapshots").select("*").order("recorded_at", { ascending: false }).limit(60)
      .then(({ data }) => {
        if (!data) return
        const latest: Record<string, RegimeSnapshot> = {}
        ;(data as RegimeSnapshot[]).forEach(r => { if (!latest[r.instrument]) latest[r.instrument] = r })
        setRegimes(Object.values(latest))
      }), [])

  const loadTodayTrades = useCallback(() => {
    const today = new Date().toISOString().slice(0, 10)
    supabase.from("trades").select("profit").gte("closed_at", today)
      .then(({ data }) => data && setTodayTrades(data as Trade[]))
  }, [])

  useEffect(() => {
    supabase.from("bot_status").select("*").order("id").limit(1).single()
      .then(({ data }) => data && setBotStatus(data as BotStatus))

    loadPositions(); loadSignals(); loadRegimes(); loadTodayTrades()

    const timer = setInterval(() => {
      setTick(t => t + 1)
      loadPositions()
      loadRegimes()
      loadTodayTrades()
    }, 30_000)

    const ch = supabase.channel("overview-rt")
      .on("postgres_changes", { event: "*",      schema: "public", table: "bot_status" },
        ({ new: row }) => setBotStatus(row as BotStatus))
      .on("postgres_changes", { event: "*",      schema: "public", table: "positions" }, loadPositions)
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "signals"   }, loadSignals)
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "trades"    }, loadTodayTrades)
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "regime_snapshots" }, loadRegimes)
      .subscribe()

    return () => { supabase.removeChannel(ch); clearInterval(timer) }
  }, [loadPositions, loadSignals, loadRegimes, loadTodayTrades])

  const floatPnl    = positions.reduce((s, p) => s + (p.profit ?? 0), 0)
  const realizedPnl = todayTrades.reduce((s, t) => s + (t.profit ?? 0), 0)
  const dailyPnl    = realizedPnl + floatPnl
  const balance     = botStatus?.balance ?? 1500
  const equity      = botStatus?.equity  ?? balance
  const equityDiff  = equity - balance

  const todayWins = todayTrades.filter(t => (t.profit ?? 0) > 0).length
  const winRate   = todayTrades.length > 0 ? todayWins / todayTrades.length : null

  const status      = botStatus?.status ?? "OFFLINE"
  const statusColor = status === "RUNNING" ? "var(--green)" : status === "ERROR" ? "var(--red)" : "var(--muted)"

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem", maxWidth: 1400 }}>

      {/* ── STATUS BAR ── */}
      <div style={{
        background: "var(--panel)",
        border: "1px solid var(--border)",
        padding: "0.85rem 1.15rem",
        display: "flex", alignItems: "center", gap: "1.5rem",
        flexWrap: "wrap",
        position: "relative", overflow: "hidden",
      }}>
        {status === "RUNNING" && <div className="scanLine" />}

        {/* Status indicator */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.65rem", flexShrink: 0, zIndex: 1 }}>
          <span style={{
            display: "inline-block", width: 8, height: 8,
            background: statusColor, flexShrink: 0,
            animation: status === "RUNNING" ? "pulse 1.2s ease-in-out infinite"
                     : status === "ERROR"   ? "pulseUrgent 0.8s ease-in-out infinite"
                     : "none",
            boxShadow: `0 0 8px ${statusColor}`,
          }} />
          <div>
            <div style={{ fontSize: "0.7rem", fontWeight: 700, letterSpacing: "0.1em", color: statusColor }}>
              {status}
            </div>
            <div style={{ fontSize: "0.49rem", color: "var(--muted)", marginTop: "0.05rem" }}>
              {botStatus?.last_heartbeat && `hb ${timeAgo(botStatus.last_heartbeat)}`}
              {botStatus?.uptime_seconds != null && ` · up ${fmtUptime(botStatus.uptime_seconds)}`}
            </div>
          </div>
        </div>

        {status === "ERROR" && botStatus?.error_message && (
          <div style={{
            fontSize: "0.58rem", color: "var(--red)",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            maxWidth: 240, padding: "0.2rem 0.55rem",
            border: "1px solid rgba(232,64,64,0.22)",
            background: "rgba(232,64,64,0.05)",
            zIndex: 1,
          }}>
            {botStatus.error_message}
          </div>
        )}

        <div style={{ width: 1, height: 30, background: "var(--border)", flexShrink: 0, zIndex: 1 }} />

        {/* Metrics */}
        <div style={{
          display: "flex", gap: "1.75rem", alignItems: "flex-end",
          flexWrap: "wrap", marginLeft: "auto", zIndex: 1,
        }}>
          {botStatus?.balance != null && (
            <Metric label="BALANCE" value={`$${balance.toFixed(2)}`} />
          )}

          {botStatus?.equity != null && (
            <Metric
              label="EQUITY"
              value={`$${equity.toFixed(2)}`}
              sub={equityDiff !== 0
                ? <span style={{ color: equityDiff >= 0 ? "var(--green)" : "var(--red)" }}>
                    {equityDiff >= 0 ? "+" : ""}{equityDiff.toFixed(2)}
                  </span>
                : undefined
              }
            />
          )}

          {winRate !== null && (
            <Metric
              label="WIN RATE"
              value={`${(winRate * 100).toFixed(0)}%`}
              sub={`${todayWins}/${todayTrades.length} trades`}
              color={winRate >= 0.6 ? "var(--green)" : winRate >= 0.45 ? "var(--yellow)" : "var(--red)"}
            />
          )}

          <div style={{ width: 1, height: 30, background: "var(--border)" }} />

          <Metric label="OPEN" value={positions.length} />

          <Metric
            label="FLOAT P&L"
            value={
              <span style={{ color: floatPnl >= 0 ? "var(--green)" : "var(--red)" }}>
                {fmtPnl(floatPnl)}
              </span>
            }
            sub="USD"
          />

          {(realizedPnl !== 0 || todayTrades.length > 0) && (
            <Metric
              label="TODAY REALIZED"
              value={
                <span style={{ color: realizedPnl >= 0 ? "var(--green)" : "var(--red)" }}>
                  {fmtPnl(realizedPnl)}
                </span>
              }
              sub={`${todayTrades.length}t`}
            />
          )}

          <DrawdownGauge used={dailyPnl < 0 ? dailyPnl : 0} balance={balance} />
        </div>
      </div>

      {/* ── REGIME STRIP ── */}
      {regimes.length > 0 && (
        <div>
          <SectionLabel>MARKET REGIMES</SectionLabel>
          <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
            {regimes.map(r => <RegimeTile key={r.instrument} r={r} />)}
          </div>
        </div>
      )}

      {/* ── BODY ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 295px", gap: "1.25rem", alignItems: "start" }}>

        {/* Position cards */}
        <div>
          <SectionLabel right={positions.length > 0 ? `${positions.length} open` : undefined}>
            OPEN POSITIONS
          </SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
            {positions.map((p, i) => (
              <PositionCard
                key={p.ticket}
                pos={p}
                index={i}
                onOpen={setDrawerItem}
              />
            ))}
            {positions.length === 0 && (
              <div style={{
                background: "var(--panel)", border: "1px solid var(--border)",
                padding: "3rem", textAlign: "center",
                fontSize: "0.65rem", color: "var(--muted)", letterSpacing: "0.06em",
              }}>
                — no open positions —
              </div>
            )}
          </div>
        </div>

        {/* Signal feed */}
        <div>
          <SectionLabel right={
            signals.length > 0
              ? `${signals.filter(s => s.executed).length} exec · ${signals.filter(s => s.ai_decision === "VETO").length} veto`
              : undefined
          }>
            SIGNAL FEED
          </SectionLabel>
          <div style={{ background: "var(--panel)", border: "1px solid var(--border)", overflow: "hidden" }}>
            {signals.map((s, i) => (
              <SignalRow
                key={s.id} s={s} i={i}
                isNew={!prevSignalIds.current.has(s.id) && prevSignalIds.current.size > 0}
                onOpen={setDrawerItem}
              />
            ))}
            {signals.length === 0 && (
              <div style={{ padding: "2rem 1rem", color: "var(--muted)", fontSize: "0.65rem", textAlign: "center" }}>
                — awaiting signals —
              </div>
            )}
          </div>
        </div>
      </div>
      <InstrumentDrawer item={drawerItem} onClose={() => setDrawerItem(null)} />
    </div>
  )
}
