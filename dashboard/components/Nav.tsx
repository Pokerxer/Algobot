"use client"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { LayoutDashboard, TrendingUp, Zap, History, BarChart2 } from "lucide-react"

const links = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/positions", label: "Positions", icon: TrendingUp },
  { href: "/signals", label: "Signals", icon: Zap },
  { href: "/trades", label: "Trades", icon: History },
  { href: "/performance", label: "Performance", icon: BarChart2 },
]

export default function Nav() {
  const path = usePathname()
  return (
    <nav style={{
      width: 200, background: "var(--surface)", borderRight: "1px solid var(--border)",
      display: "flex", flexDirection: "column", padding: "1.5rem 1rem", gap: "0.25rem",
      flexShrink: 0,
    }}>
      <div style={{ marginBottom: "1.5rem" }}>
        <div style={{ fontSize: "0.7rem", color: "var(--muted)", letterSpacing: "0.1em" }}>ALGOBOT</div>
        <div style={{ fontSize: "1rem", fontWeight: 700, color: "var(--text)" }}>Monitor</div>
      </div>
      {links.map(({ href, label, icon: Icon }) => {
        const active = path === href
        return (
          <Link key={href} href={href} style={{
            display: "flex", alignItems: "center", gap: "0.6rem",
            padding: "0.5rem 0.75rem", borderRadius: 6,
            fontSize: "0.85rem",
            background: active ? "var(--border)" : "transparent",
            color: active ? "var(--text)" : "var(--muted)",
            transition: "background 0.15s",
          }}>
            <Icon size={15} />
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
