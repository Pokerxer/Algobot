import type { Metadata } from "next"
import "./globals.css"
import Nav from "@/components/Nav"

export const metadata: Metadata = {
  title: "ALGOBOT — Terminal",
  description: "MT5 agentic trading bot — live monitor",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body suppressHydrationWarning style={{ display: "flex", minHeight: "100vh" }}>
        <Nav />
        <main style={{
          flex: 1,
          padding: "1.5rem 1.75rem",
          overflowY: "auto",
          minWidth: 0,
        }}>
          {children}
        </main>
      </body>
    </html>
  )
}
