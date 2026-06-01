"use client"
import { useEffect, useRef, useState, useCallback } from "react"
import { supabase } from "@/lib/supabase"
import type { BotStatus, Position, RegimeSnapshot, Signal, Trade } from "@/lib/types"
import { fmtPrice, fmtPnl, fmtPips, fmtPct, timeAgo } from "@/lib/fmt"

const MAX_HOLDING_HOURS = 24
const MAX_DRAWDOWN_PCT  = 0.05   // 5 %

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
      const e = 1 - Math.pow(1 - p, 3)                 // cubic ease-out
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
  // 0 = at SL (danger), 1 = at TP (safe)
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

  // For labels: left always = SL, right always = TP (regardless of direction)
  const leftPrice  = sl
  const rightPrice = tp
  const slPips     = fmtPips(Math.abs(current - sl), instrument)
  const tpPips     = fmtPips(Math.abs(tp - current), instrument)

  return (
    <div style={{ margin: "0.75rem 0 0.45rem" }}>
      <div style={{ position: "relative", height: 8, background: "var(--border)", overflow: "visible" }}>
        {/* Fill */}
        <div style={{
          position: "absolute", left: 0, height: "100%",
          width: `${currentPct * 100}%`,
          background: fillColor, opacity: 0.5,
          transition: "width 0.7s cubic-bezier(0.16,1,0.3,1)",
        }} />
        {/* Entry marker */}
        <div style={{
          position: "absolute", left: `${entryPct * 100}%`,
          top: -1, height: 10, width: 2,
          background: "var(--sub)", transform: "translateX(-1px)",
        }} />
        {/* Current-price tick with glow */}
        <div style={{
          position: "absolute", left: `${currentPct * 100}%`,
          top: -4, height: 16, width: 3,
          background: fillColor,
          transform: "translateX(-1.5px)",
          boxShadow: `0 0 8px ${fillColor}`,
          transition: "left 0.7s cubic-bezier(0.16,1,0.3,1), background 0.4s",
        }} />
      </div>
      {/* Floor labels */}
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.35rem", fontSize: "0.6rem" }}>
        <span style={{ color: "var(--red)" }}>
          SL {fmtPrice(leftPrice, instrument)}
          <span style={{ color: "var(--muted)", marginLeft: "0.3rem" }}>←{slPips}p</span>
        </span>
        <span style={{ color: "var(--muted)", fontSize: "0.58rem" }}>
          entry {fmtPrice(entry, instrument)}
        </span>
        <span style={{ color: "var(--teal)" }}>
          <span style={{ color: "var(--muted)", marginRight: "0.3rem" }}>{tpPips}p→</span>
          TP {fmtPrice(rightPrice, instrument)}
        </span>
      </div>
    </div>
  )
}

/* ── POSITION CARD ──────────────────────────────────────────── */
function PositionCard({ pos, index }: { pos: Position, index: number }) {
  const rawPnl  = pos.profit ?? 0
  const animPnl = useAnimatedValue(rawPnl, 600)
  const prox    = proximity(pos)
  const age     = agePct(pos.opened_at)
  const danger  = prox < 0.18                  // within 18 % of SL
  const rr      = pos.stop_loss && pos.take_profit
    ? Math.abs(pos.take_profit - pos.entry_price) / Math.abs(pos.entry_price - pos.stop_loss)
    : null

  // Current price color: green if moving in profitable direction, red otherwise
  const cur       = pos.current_price ?? pos.entry_price
  const curGreen  = pos.direction === "BUY" ? cur >= pos.entry_price : cur <= pos.entry_price

  const borderColor = danger            ? "rgba(232,64,64,0.45)"
                    : rawPnl > 0        ? "rgba(0,200,122,0.28)"
                    : rawPnl < 0        ? "rgba(232,64,64,0.18)"
                    : "var(--border)"

  return (
    <div className="cardIn" style={{
      background: "var(--panel)",
      border: `1px solid ${borderColor}`,
      padding: "0.95rem 1.1rem",
      position: "relative", overflow: "hidden",
      animationDelay: `${index * 0.08}s`,
      animation: danger
        ? `cardIn 0.35s cubic-bezier(0.16,1,0.3,1) ${index * 0.08}s both, dangerFlash 1.4s ease-in-out infinite`
        : undefined,
    }}>
      {/* Subtle directional glow */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: rawPnl > 0
          ? "radial-gradient(ellipse at 90% 10%, rgba(0,200,122,0.05) 0%, transparent 55%)"
          : rawPnl < 0
          ? "radial-gradient(ellipse at 90% 10%, rgba(232,64,64,0.04) 0%, transparent 55%)"
          : "none",
      }} />

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.55rem" }}>
          <span style={{ fontSize: "1rem", fontWeight: 700 }}>{pos.instrument}</span>
          <span style={{
            fontSize: "0.62rem", fontWeight: 700, padding: "0.12rem 0.45rem",
            background: pos.direction === "BUY" ? "rgba(0,200,122,0.15)" : "rgba(232,64,64,0.15)",
            color: pos.direction === "BUY" ? "var(--green)" : "var(--red)",
            letterSpacing: "0.06em",
          }}>{pos.direction}</span>
          <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>{pos.volume} lots</span>
          {danger && (
            <span style={{
              fontSize: "0.58rem", letterSpacing: "0.1em", color: "var(--red)",
              animation: "pulseUrgent 0.9s ease-in-out infinite",
            }}>⚠ NEAR SL</span>
          )}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: "0.58rem", color: "var(--dim)" }}>#{pos.ticket}</div>
          <div style={{ fontSize: "0.62rem", color: "var(--muted)" }}>{timeAgo(pos.opened_at)}</div>
        </div>
      </div>

      {/* Prices */}
      <div style={{ display: "flex", gap: "2.5rem", marginTop: "0.55rem" }}>
        <div>
          <div style={{ fontSize: "0.55rem", letterSpacing: "0.1em", color: "var(--muted)", marginBottom: "0.1rem" }}>ENTRY</div>
          <div style={{ fontSize: "0.85rem", fontVariantNumeric: "tabular-nums" }}>
            {fmtPrice(pos.entry_price, pos.instrument)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: "0.55rem", letterSpacing: "0.1em", color: "var(--muted)", marginBottom: "0.1rem" }}>CURRENT</div>
          <div style={{
            fontSize: "0.85rem", fontWeight: 600, fontVariantNumeric: "tabular-nums",
            color: curGreen ? "var(--green)" : "var(--red)",
            transition: "color 0.4s",
          }}>
            {fmtPrice(pos.current_price, pos.instrument)}
          </div>
        </div>
      </div>

      {/* Price bar */}
      <PriceRangeBar pos={pos} />

      {/* Footer */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "0.6rem" }}>
        <div style={{
          fontSize: "1.05rem", fontWeight: 700, fontVariantNumeric: "tabular-nums",
          color: animPnl >= 0 ? "var(--green)" : "var(--red)",
          transition: "color 0.4s",
        }}>
          {animPnl >= 0 ? "+" : ""}{animPnl.toFixed(2)}
          <span style={{ fontSize: "0.62rem", fontWeight: 400, color: "var(--muted)", marginLeft: "0.3rem" }}>USD</span>
        </div>
        <div style={{ display: "flex", gap: "0.85rem", fontSize: "0.65rem", color: "var(--muted)" }}>
          {rr != null && (
            <span style={{ color: rr >= 2 ? "var(--accent)" : rr >= 1.5 ? "var(--sub)" : "var(--muted)" }}>
              R/R {rr.toFixed(2)}:1
            </span>
          )}
          <span>{pos.strategy ?? "—"}</span>
        </div>
      </div>

      {/* Age bar — time held vs 24h max */}
      <div style={{ marginTop: "0.55rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.55rem", color: "var(--dim)", marginBottom: "0.2rem" }}>
          <span>time held</span>
          <span style={{ color: age > 0.85 ? "var(--red)" : "var(--muted)" }}>
            {(age * 100).toFixed(0)}% of {MAX_HOLDING_HOURS}h limit
          </span>
        </div>
        <div style={{ height: 2, background: "var(--border-hi)" }}>
          <div style={{
            width: `${age * 100}%`, height: "100%",
            background: age > 0.85 ? "var(--red)" : age > 0.6 ? "var(--yellow)" : "var(--dim)",
            transition: "width 0.5s",
          }} />
        </div>
      </div>
    </div>
  )
}

/* ── REGIME TILE ────────────────────────────────────────────── */
function RegimeTile({ r }: { r: RegimeSnapshot }) {
  const color = r.regime === "TRENDING_UP"   ? "var(--green)"
              : r.regime === "TRENDING_DOWN"  ? "var(--red)"
              : r.regime === "RANGING"         ? "var(--accent)"
              : "var(--muted)"
  const label = r.regime === "TRENDING_UP"   ? "↑ TREND"
              : r.regime === "TRENDING_DOWN"  ? "↓ TREND"
              : r.regime === "RANGING"         ? "⇔ RANGE"
              : "~ CHOPPY"
  const conf  = r.confidence ?? 0

  // Grey out tile if snapshot is older than 5 minutes — bot may have stopped cycling
  const staleMs = r.recorded_at ? Date.now() - new Date(r.recorded_at).getTime() : 0
  const isStale = staleMs > 5 * 60 * 1000
  const tileColor = isStale ? "var(--muted)" : color

  return (
    <div style={{
      background: "var(--panel)",
      border: `1px solid ${isStale ? "var(--border)" : "var(--border)"}`,
      padding: "0.65rem 0.9rem", minWidth: 105,
      opacity: isStale ? 0.5 : 1,
      transition: "opacity 0.4s",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.2rem" }}>
        <div style={{ fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.03em" }}>
          {r.instrument}
        </div>
        {isStale && (
          <span style={{ fontSize: "0.5rem", color: "var(--muted)", letterSpacing: "0.06em" }}>STALE</span>
        )}
      </div>
      <div style={{ fontSize: "0.65rem", color: tileColor, letterSpacing: "0.04em", marginBottom: "0.35rem" }}>
        {label}
      </div>
      {/* Confidence bar */}
      <div style={{ height: 2, background: "var(--border-hi)", marginBottom: "0.3rem" }}>
        <div style={{ width: `${conf * 100}%`, height: "100%", background: tileColor, opacity: 0.65, transition: "width 0.4s" }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.58rem", color: "var(--muted)" }}>
        <span>
          {r.adx != null ? `ADX ${r.adx.toFixed(1)}` : ""}
          {r.bb_width != null ? `  BBW ${r.bb_width.toFixed(4)}` : ""}
        </span>
        <span style={{ color: conf < 0.01 ? "var(--dim)" : "var(--muted)" }}>
          {conf < 0.01 ? "no data" : fmtPct(conf)}
        </span>
      </div>
      {r.recorded_at && (
        <div style={{ fontSize: "0.5rem", color: "var(--dim)", marginTop: "0.25rem" }}>
          {timeAgo(r.recorded_at)}
        </div>
      )}
    </div>
  )
}

/* ── SIGNAL ROW ─────────────────────────────────────────────── */
function SignalRow({ s, i, isNew }: { s: Signal, i: number, isNew: boolean }) {
  const borderColor = s.executed             ? "var(--green)"
                    : s.ai_decision === "VETO" ? "var(--red)"
                    : "var(--border)"

  return (
    <div className={isNew ? "slideFromTop" : "fadein"} style={{
      padding: "0.6rem 0.75rem 0.6rem 0.85rem",
      borderTop: i === 0 ? "none" : "1px solid var(--border)",
      borderLeft: `2px solid ${borderColor}`,
      animationDelay: isNew ? "0s" : `${i * 0.025}s`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
        <span style={{
          fontSize: "0.6rem", fontWeight: 700, padding: "0.08rem 0.3rem",
          background: s.direction === "BUY" ? "rgba(0,200,122,0.15)" : "rgba(232,64,64,0.15)",
          color: s.direction === "BUY" ? "var(--green)" : "var(--red)",
        }}>{s.direction}</span>
        <span style={{ fontSize: "0.75rem", fontWeight: 600 }}>{s.instrument}</span>
        {s.executed && (
          <span style={{ fontSize: "0.55rem", letterSpacing: "0.08em", color: "var(--accent)" }}>EXEC</span>
        )}
        <span style={{ marginLeft: "auto", fontSize: "0.58rem", color: "var(--muted)" }}>
          {timeAgo(s.created_at)}
        </span>
      </div>
      <div style={{ display: "flex", gap: "0.6rem", marginTop: "0.2rem", fontSize: "0.62rem", color: "var(--muted)" }}>
        {s.confidence != null && <span>{(s.confidence * 100).toFixed(0)}%</span>}
        <span>{s.strategy ?? ""}</span>
        {s.ai_decision && (
          <span style={{
            marginLeft: "auto",
            color: s.ai_decision === "APPROVE" ? "var(--green)"
                 : s.ai_decision === "VETO"    ? "var(--red)"
                 : "var(--yellow)",
          }}>
            {s.ai_decision === "APPROVE" ? "✓" : s.ai_decision === "VETO" ? "✗" : "↻"} {s.ai_decision}
          </span>
        )}
      </div>
      {s.ai_reasoning && (
        <div style={{
          marginTop: "0.2rem", fontSize: "0.58rem", color: "var(--dim)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>{s.ai_reasoning}</div>
      )}
    </div>
  )
}

/* ── DRAWDOWN GAUGE ─────────────────────────────────────────── */
function DrawdownGauge({ used, balance }: { used: number, balance: number }) {
  const limit  = balance * MAX_DRAWDOWN_PCT
  const pct    = limit > 0 ? Math.min(Math.abs(used) / limit, 1) : 0
  const color  = pct > 0.75 ? "var(--red)" : pct > 0.4 ? "var(--yellow)" : "var(--green)"

  return (
    <div style={{ textAlign: "right" }}>
      <div style={{ fontSize: "0.55rem", letterSpacing: "0.12em", color: "var(--muted)", marginBottom: "0.25rem" }}>
        DAILY DRAWDOWN
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", justifyContent: "flex-end" }}>
        <div style={{ width: 60, height: 4, background: "var(--border-hi)" }}>
          <div style={{
            width: `${pct * 100}%`, height: "100%", background: color,
            transition: "width 0.5s, background 0.4s",
          }} />
        </div>
        <span style={{ fontSize: "0.7rem", fontWeight: 600, color, fontVariantNumeric: "tabular-nums" }}>
          {(pct * 100).toFixed(0)}%
        </span>
      </div>
      <div style={{ fontSize: "0.58rem", color: "var(--muted)", marginTop: "0.1rem" }}>
        ${Math.abs(used).toFixed(2)} / ${limit.toFixed(2)} limit
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

  // Track new signal IDs for slide-in animation
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

    // Refresh positions + regimes + time-ago strings every 30s.
    // Regime realtime fires only on INSERT — the 30s poll catches any missed updates.
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

  // Live balance & equity from bot_status — updated every 60s cycle, no stale daily snapshot
  const balance     = botStatus?.balance ?? 1500
  const equity      = botStatus?.equity  ?? balance
  const equityDiff  = equity - balance   // positive = unrealized gain, negative = drawdown

  // Today's win rate from closed trades
  const todayWins   = todayTrades.filter(t => (t.profit ?? 0) > 0).length
  const winRate     = todayTrades.length > 0 ? todayWins / todayTrades.length : null

  const status      = botStatus?.status ?? "OFFLINE"
  const statusColor = status === "RUNNING" ? "var(--green)" : status === "ERROR" ? "var(--red)" : "var(--muted)"

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem", maxWidth: 1400 }}>

      {/* ── STATUS HEADER ── */}
      <div style={{
        display: "flex", alignItems: "center", gap: "1.5rem",
        borderBottom: "1px solid var(--border)", paddingBottom: "0.9rem",
        flexWrap: "wrap",
      }}>
        {/* Status */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span style={{
            display: "inline-block", width: 7, height: 7, borderRadius: "50%",
            background: statusColor, color: statusColor, flexShrink: 0,
            animation: status === "RUNNING" ? "pulse 1.2s ease-in-out infinite"
                     : status === "ERROR"   ? "pulseUrgent 0.8s ease-in-out infinite"
                     : "none",
            boxShadow: `0 0 6px ${statusColor}`,
          }} />
          <span style={{ fontSize: "0.72rem", fontWeight: 600, letterSpacing: "0.08em", color: statusColor }}>
            {status}
          </span>
        </div>

        {botStatus?.last_heartbeat && (
          <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>
            hb {timeAgo(botStatus.last_heartbeat)} ago
          </span>
        )}

        {botStatus?.uptime_seconds != null && (
          <span style={{ fontSize: "0.65rem", color: "var(--dim)" }}>
            up {fmtUptime(botStatus.uptime_seconds)}
          </span>
        )}

        {status === "ERROR" && botStatus?.error_message && (
          <span style={{ fontSize: "0.65rem", color: "var(--red)", maxWidth: 260,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {botStatus.error_message}
          </span>
        )}

        {/* Right side metrics */}
        <div style={{ marginLeft: "auto", display: "flex", gap: "2rem", alignItems: "flex-end", flexWrap: "wrap" }}>

          {/* Balance — live from bot_status, not stale performance_daily */}
          {botStatus?.balance != null && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: "0.55rem", letterSpacing: "0.12em", color: "var(--muted)" }}>BALANCE</div>
              <div style={{ fontSize: "1.1rem", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
                ${balance.toFixed(2)}
              </div>
            </div>
          )}

          {/* Equity — shows unrealized exposure vs balance */}
          {botStatus?.equity != null && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: "0.55rem", letterSpacing: "0.12em", color: "var(--muted)" }}>EQUITY</div>
              <div style={{ fontSize: "1.1rem", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
                ${equity.toFixed(2)}
                {equityDiff !== 0 && (
                  <span style={{
                    fontSize: "0.6rem", fontWeight: 400, marginLeft: "0.3rem",
                    color: equityDiff >= 0 ? "var(--green)" : "var(--red)",
                  }}>
                    {equityDiff >= 0 ? "+" : ""}{equityDiff.toFixed(2)}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Win rate — today's closed trades */}
          {winRate !== null && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: "0.55rem", letterSpacing: "0.12em", color: "var(--muted)" }}>WIN RATE</div>
              <div style={{
                fontSize: "1.1rem", fontWeight: 700, fontVariantNumeric: "tabular-nums",
                color: winRate >= 0.6 ? "var(--green)" : winRate >= 0.45 ? "var(--yellow)" : "var(--red)",
              }}>
                {(winRate * 100).toFixed(0)}%
                <span style={{ fontSize: "0.6rem", fontWeight: 400, color: "var(--muted)", marginLeft: "0.3rem" }}>
                  {todayWins}/{todayTrades.length}
                </span>
              </div>
            </div>
          )}

          {/* Separator */}
          <div style={{ width: 1, height: 32, background: "var(--border)", alignSelf: "center" }} />

          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: "0.55rem", letterSpacing: "0.12em", color: "var(--muted)" }}>OPEN</div>
            <div style={{ fontSize: "1.1rem", fontWeight: 700 }}>{positions.length}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: "0.55rem", letterSpacing: "0.12em", color: "var(--muted)" }}>FLOAT P&amp;L</div>
            <div style={{
              fontSize: "1.1rem", fontWeight: 700, fontVariantNumeric: "tabular-nums",
              color: floatPnl >= 0 ? "var(--green)" : "var(--red)", transition: "color 0.4s",
            }}>
              {fmtPnl(floatPnl)}
              <span style={{ fontSize: "0.62rem", color: "var(--muted)", fontWeight: 400, marginLeft: "0.25rem" }}>USD</span>
            </div>
          </div>
          {(realizedPnl !== 0 || todayTrades.length > 0) && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: "0.55rem", letterSpacing: "0.12em", color: "var(--muted)" }}>TODAY REALIZED</div>
              <div style={{
                fontSize: "1.1rem", fontWeight: 700, fontVariantNumeric: "tabular-nums",
                color: realizedPnl >= 0 ? "var(--green)" : "var(--red)",
              }}>
                {fmtPnl(realizedPnl)}
                <span style={{ fontSize: "0.62rem", color: "var(--muted)", fontWeight: 400, marginLeft: "0.25rem" }}>
                  ({todayTrades.length}t)
                </span>
              </div>
            </div>
          )}
          <DrawdownGauge used={dailyPnl < 0 ? dailyPnl : 0} balance={balance} />
        </div>
      </div>

      {/* ── REGIME STRIP ── */}
      {regimes.length > 0 && (
        <div>
          <div style={{ fontSize: "0.58rem", letterSpacing: "0.14em", color: "var(--muted)", marginBottom: "0.5rem" }}>
            MARKET REGIMES
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {regimes.map(r => <RegimeTile key={r.instrument} r={r} />)}
          </div>
        </div>
      )}

      {/* ── BODY ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: "1.25rem", alignItems: "start" }}>

        {/* Position cards */}
        <div>
          <div style={{ fontSize: "0.58rem", letterSpacing: "0.14em", color: "var(--muted)", marginBottom: "0.5rem" }}>
            OPEN POSITIONS
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {positions.map((p, i) => <PositionCard key={p.ticket} pos={p} index={i} />)}
            {positions.length === 0 && (
              <div style={{
                background: "var(--panel)", border: "1px solid var(--border)",
                padding: "2.5rem", textAlign: "center",
                fontSize: "0.72rem", color: "var(--muted)", letterSpacing: "0.04em",
              }}>— no open positions —</div>
            )}
          </div>
        </div>

        {/* Signal feed */}
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
            <div style={{ fontSize: "0.58rem", letterSpacing: "0.14em", color: "var(--muted)" }}>SIGNAL FEED</div>
            {signals.length > 0 && (
              <span style={{ fontSize: "0.58rem", color: "var(--dim)", marginLeft: "auto" }}>
                {signals.filter(s => s.executed).length} exec
                {" · "}
                {signals.filter(s => s.ai_decision === "VETO").length} veto
              </span>
            )}
          </div>
          <div style={{ background: "var(--panel)", border: "1px solid var(--border)", overflow: "hidden" }}>
            {signals.map((s, i) => (
              <SignalRow
                key={s.id} s={s} i={i}
                isNew={!prevSignalIds.current.has(s.id) && prevSignalIds.current.size > 0}
              />
            ))}
            {signals.length === 0 && (
              <div style={{ padding: "1.5rem", color: "var(--muted)", fontSize: "0.72rem", textAlign: "center" }}>
                — awaiting signals —
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
