"use client"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"

const links = [
  { href: "/",            label: "OVERVIEW",    key: "F1" },
  { href: "/positions",   label: "POSITIONS",   key: "F2" },
  { href: "/signals",     label: "SIGNALS",     key: "F3" },
  { href: "/trades",      label: "TRADES",      key: "F4" },
  { href: "/performance", label: "PERFORMANCE", key: "F5" },
  { href: "/insight",     label: "INSIGHT",     key: "F6" },
]

export default function Nav() {
  const path = usePathname()
  const [time, setTime] = useState("")

  useEffect(() => {
    const tick = () => setTime(new Date().toLocaleTimeString("en-GB", { hour12: false }))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <nav style={{
      width: 176,
      flexShrink: 0,
      background: "var(--surface)",
      borderRight: "1px solid var(--border)",
      display: "flex",
      flexDirection: "column",
      height: "100vh",
      position: "sticky",
      top: 0,
    }}>
      {/* Brand */}
      <div style={{
        padding: "1.25rem 1rem 1rem",
        borderBottom: "1px solid var(--border)",
      }}>
        <div style={{
          fontSize: "0.6rem",
          letterSpacing: "0.18em",
          color: "var(--muted)",
          marginBottom: "0.15rem",
        }}>
          MT5 TRADING SYSTEM
        </div>
        <div style={{
          fontSize: "1.05rem",
          fontWeight: 600,
          letterSpacing: "0.05em",
          color: "var(--accent)",
        }}>
          ALGOBOT
        </div>
      </div>

      {/* Links */}
      <div style={{ padding: "0.75rem 0", flex: 1 }}>
        {links.map(({ href, label, key }) => {
          const active = path === href
          return (
            <Link key={href} href={href} style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "0.55rem 1rem",
              fontSize: "0.7rem",
              letterSpacing: "0.06em",
              fontWeight: active ? 500 : 400,
              color: active ? "var(--text)" : "var(--muted)",
              background: active ? "var(--accent-dim)" : "transparent",
              borderLeft: active ? "2px solid var(--accent)" : "2px solid transparent",
              transition: "all 0.1s",
            }}>
              <span>{label}</span>
              <span style={{ fontSize: "0.58rem", color: "var(--dim)", fontWeight: 400 }}>{key}</span>
            </Link>
          )
        })}
      </div>

      {/* Footer */}
      <div style={{
        padding: "0.75rem 1rem",
        borderTop: "1px solid var(--border)",
        fontSize: "0.65rem",
        color: "var(--muted)",
      }}>
        <div style={{ color: "var(--dim)", marginBottom: "0.2rem" }}>UTC</div>
        <div style={{ fontVariantNumeric: "tabular-nums", letterSpacing: "0.04em" }}>
          {time || "—"}
        </div>
        <div style={{ marginTop: "0.5rem", color: "var(--dim)", fontSize: "0.58rem" }}>
          v0.1.0
        </div>
      </div>
    </nav>
  )
}
