export interface BotStatus {
  id: number
  status: "RUNNING" | "STOPPED" | "ERROR"
  last_heartbeat: string | null
  error_message: string | null
  uptime_seconds: number | null
  updated_at: string
}

export interface Position {
  id: number
  ticket: number
  instrument: string
  direction: "BUY" | "SELL"
  entry_price: number
  current_price: number | null
  volume: number
  profit: number | null
  stop_loss: number | null
  take_profit: number | null
  opened_at: string
  strategy: string | null
  regime: string | null
}

export interface Signal {
  id: number
  instrument: string
  direction: string
  confidence: number | null
  regime: string | null
  strategy: string | null
  ai_decision: string | null
  ai_reasoning: string | null
  executed: boolean
  created_at: string
}

export interface Trade {
  id: number
  ticket: number
  instrument: string
  direction: string | null
  entry_price: number | null
  exit_price: number | null
  volume: number | null
  profit: number | null
  opened_at: string | null
  closed_at: string | null
  strategy: string | null
  regime: string | null
  ai_decision: string | null
  duration_minutes: number | null
}

export interface RegimeSnapshot {
  id: number
  instrument: string
  regime: string
  adx: number | null
  bb_width: number | null
  confidence: number | null
  recorded_at: string
}

export interface PerformanceDaily {
  id: number
  date: string
  total_trades: number | null
  win_rate: number | null
  profit: number | null
  drawdown: number | null
  balance: number | null
  sharpe: number | null
}
