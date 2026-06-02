"use client"
import { useEffect, useRef } from "react"
import type { Position, Trade } from "@/lib/types"

// Minimal TV widget typings — only what we actually call.
interface TVPositionLine {
  setPrice(n: number): TVPositionLine
  setText(s: string): TVPositionLine
  setQuantity(s: string): TVPositionLine
  setLineColor(s: string): TVPositionLine
  setBodyBackgroundColor(s: string): TVPositionLine
  setBodyTextColor(s: string): TVPositionLine
  setLineStyle(n: number): TVPositionLine
  setLineLength(n: number): TVPositionLine
}

interface TVChartAPI {
  createPositionLine(): TVPositionLine
  createShape(
    point: { time: number; price?: number },
    opts: { shape: string; overrides?: Record<string, unknown>; text?: string }
  ): unknown
}

declare global {
  interface TVWidget {
    remove(): void
    onChartReady(fn: () => void): void
    chart(): TVChartAPI
    activeChart(): TVChartAPI
  }
  interface Window {
    TradingView?: { widget: new (opts: Record<string, unknown>) => TVWidget }
    _tvScriptPromise?: Promise<void>
  }
}

function loadTVScript(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve()
  if (window._tvScriptPromise) return window._tvScriptPromise
  window._tvScriptPromise = new Promise(resolve => {
    const s = document.createElement("script")
    s.src = "https://s3.tradingview.com/tv.js"
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => resolve()
    document.head.appendChild(s)
  })
  return window._tvScriptPromise
}

/** Strip Exness 'm' suffix and map index symbols to TradingView equivalents. */
export function tvSymbol(instrument: string): string {
  const s = instrument.replace(/m$/, "")
  if (s === "US500") return "CAPITALCOM:US500"
  if (s === "US30")  return "CAPITALCOM:US30"
  return s
}

function addOverlays(widget: TVWidget, cancelled: () => boolean, position?: Position, trades?: Trade[]) {
  widget.onChartReady(() => {
    if (cancelled()) return
    const chart: TVChartAPI = (widget as any).activeChart?.() ?? widget.chart()
    if (!chart) return

    // ── current open position: entry line + SL line + TP line ──────────────
    if (position) {
      const isBuy   = position.direction === "BUY"
      const pnlStr  = position.profit != null
        ? ` ${position.profit >= 0 ? "+" : ""}${position.profit.toFixed(2)}`
        : ""
      const entryColor = isBuy ? "#00C87A" : "#E84040"

      try {
        chart.createPositionLine()
          .setPrice(position.entry_price)
          .setText(isBuy ? "▲ LONG" : "▼ SHORT")
          .setQuantity(`${position.volume}L${pnlStr}`)
          .setLineColor(entryColor)
          .setBodyBackgroundColor(isBuy ? "rgba(0,200,122,0.15)" : "rgba(232,64,64,0.15)")
          .setBodyTextColor(entryColor)
          .setLineStyle(0)
          .setLineLength(0)
      } catch {}

      if (position.stop_loss) {
        try {
          chart.createPositionLine()
            .setPrice(position.stop_loss)
            .setText("SL")
            .setQuantity("")
            .setLineColor("#E84040")
            .setBodyBackgroundColor("rgba(232,64,64,0.12)")
            .setBodyTextColor("#E84040")
            .setLineStyle(2)
            .setLineLength(25)
        } catch {}
      }

      if (position.take_profit) {
        try {
          chart.createPositionLine()
            .setPrice(position.take_profit)
            .setText("TP")
            .setQuantity("")
            .setLineColor("#00C8BE")
            .setBodyBackgroundColor("rgba(0,200,190,0.12)")
            .setBodyTextColor("#00C8BE")
            .setLineStyle(2)
            .setLineLength(25)
        } catch {}
      }
    }

    // ── past closed trades: entry arrow (direction) + exit flag ────────────
    trades?.forEach(trade => {
      if (!trade.opened_at || trade.entry_price == null) return
      const isBuy   = trade.direction === "BUY"
      const win     = (trade.profit ?? 0) > 0
      const color   = win ? "#00C87A" : "#E84040"
      const entryT  = Math.floor(new Date(trade.opened_at).getTime() / 1000)

      try {
        chart.createShape(
          { time: entryT, price: trade.entry_price },
          {
            shape: isBuy ? "arrow_up" : "arrow_down",
            overrides: { color },
          }
        )
      } catch {}

      if (trade.closed_at && trade.exit_price != null) {
        const exitT = Math.floor(new Date(trade.closed_at).getTime() / 1000)
        try {
          chart.createShape(
            { time: exitT, price: trade.exit_price },
            {
              shape: "flag",
              overrides: { color },
            }
          )
        } catch {}
      }
    })
  })
}

type TVStudy = string | { id: string; inputs?: Record<string, unknown> }

export function TradingViewChart({
  symbol,
  studies,
  position,
  trades,
}: {
  symbol:    string
  studies?:  TVStudy[]
  position?: Position
  trades?:   Trade[]
}) {
  const id           = `tv_${symbol.replace(/\W/g, "_")}`
  const containerRef = useRef<HTMLDivElement>(null)
  // Ref so addOverlays always reads the latest data without being a dep.
  const overlaysRef  = useRef({ position, trades })
  overlaysRef.current = { position, trades }

  useEffect(() => {
    if (!symbol) return
    let cancelledFlag = false
    const cancelled   = () => cancelledFlag
    let widget: TVWidget | null = null

    loadTVScript().then(() => {
      if (cancelledFlag || !window.TradingView) return
      if (containerRef.current) containerRef.current.innerHTML = ""
      widget = new window.TradingView.widget({
        autosize:          true,
        symbol,
        interval:          "H1",
        timezone:          "Etc/UTC",
        theme:             "dark",
        style:             "1",
        locale:            "en",
        toolbar_bg:        "#0D0D11",
        enable_publishing: false,
        hide_top_toolbar:  false,
        hide_legend:       false,
        save_image:        false,
        container_id:      id,
        ...(studies && studies.length > 0 ? { studies } : {}),
      })
      addOverlays(widget, cancelled, overlaysRef.current.position, overlaysRef.current.trades)
    })

    return () => {
      cancelledFlag = true
      if (widget) widget.remove()
    }
  }, [id, symbol, studies]) // position/trades intentionally omitted — read from ref at chart-ready time

  return <div id={id} ref={containerRef} style={{ width: "100%", height: 320 }} />
}
