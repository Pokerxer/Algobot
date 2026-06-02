"use client"
import { useEffect, useRef } from "react"

declare global {
  interface TVWidget {
    remove(): void
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

/**
 * Embeds a TradingView Advanced Chart for the given symbol.
 * Use key={symbol} at the call site to force remount on symbol change.
 */
export function TradingViewChart({ symbol }: { symbol: string }) {
  const id = `tv_${symbol.replace(/\W/g, "_")}`
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    let widget: TVWidget | null = null
    loadTVScript().then(() => {
      if (cancelled || !window.TradingView) return
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
      })
    })
    return () => {
      cancelled = true
      if (widget) widget.remove()
    }
  }, [id, symbol])

  return <div id={id} ref={containerRef} style={{ width: "100%", height: 320 }} />
}
