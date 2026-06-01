export function fmtPrice(v: number | null, inst: string): string {
  if (v == null) return "—"
  if (inst.includes("JPY")) return v.toFixed(3)
  if (inst.includes("XAU") || /US[35]|US30/.test(inst)) return v.toFixed(2)
  return v.toFixed(5)
}

export function fmtPips(dist: number, inst: string): string {
  if (inst.includes("JPY")) return (dist * 100).toFixed(1)
  if (inst.includes("XAU") || /US[35]|US30/.test(inst)) return dist.toFixed(2)
  return (dist * 10000).toFixed(1)
}

export function fmtPnl(v: number | null): string {
  if (v == null) return "—"
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}`
}

export function fmtPct(v: number | null): string {
  if (v == null) return "—"
  return `${(v * 100).toFixed(1)}%`
}

export function fmtDur(m: number | null): string {
  if (m == null) return "—"
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60), r = m % 60
  return r > 0 ? `${h}h ${r}m` : `${h}h`
}

export function fmtTime(d: string | null, opts?: { date?: boolean }): string {
  if (!d) return "—"
  const dt = new Date(d)
  if (opts?.date) {
    return dt.toLocaleString("en-GB", {
      month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).replace(",", "")
  }
  return dt.toLocaleTimeString("en-GB", { hour12: false })
}

export function timeAgo(d: string): string {
  const ms = Date.now() - new Date(d).getTime()
  const m = Math.floor(ms / 60000)
  if (m < 1) return "<1m"
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`
}
