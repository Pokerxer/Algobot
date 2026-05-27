CREATE TABLE positions (
  id BIGSERIAL PRIMARY KEY,
  ticket BIGINT UNIQUE NOT NULL,
  instrument TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('BUY','SELL')),
  entry_price NUMERIC NOT NULL,
  current_price NUMERIC,
  volume NUMERIC NOT NULL,
  profit NUMERIC,
  stop_loss NUMERIC,
  take_profit NUMERIC,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  strategy TEXT,
  regime TEXT
);

CREATE TABLE trades (
  id BIGSERIAL PRIMARY KEY,
  ticket BIGINT NOT NULL,
  instrument TEXT NOT NULL,
  direction TEXT, entry_price NUMERIC, exit_price NUMERIC,
  volume NUMERIC, profit NUMERIC,
  opened_at TIMESTAMPTZ, closed_at TIMESTAMPTZ,
  strategy TEXT, regime TEXT,
  ai_decision TEXT, ai_reasoning TEXT,
  duration_minutes INT
);

CREATE TABLE signals (
  id BIGSERIAL PRIMARY KEY,
  instrument TEXT NOT NULL, direction TEXT NOT NULL,
  confidence NUMERIC, regime TEXT, strategy TEXT,
  ai_decision TEXT, ai_reasoning TEXT,
  executed BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE regime_snapshots (
  id BIGSERIAL PRIMARY KEY,
  instrument TEXT NOT NULL, regime TEXT NOT NULL,
  adx NUMERIC, bb_width NUMERIC, confidence NUMERIC,
  recorded_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE performance_daily (
  id BIGSERIAL PRIMARY KEY,
  date DATE UNIQUE NOT NULL,
  total_trades INT, win_rate NUMERIC, profit NUMERIC,
  drawdown NUMERIC, balance NUMERIC, sharpe NUMERIC
);

CREATE TABLE bot_status (
  id BIGSERIAL PRIMARY KEY,
  status TEXT NOT NULL,
  last_heartbeat TIMESTAMPTZ,
  error_message TEXT, uptime_seconds INT,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_trades_closed_at ON trades(closed_at DESC);
CREATE INDEX idx_signals_created_at ON signals(created_at DESC);
CREATE INDEX idx_regime_recorded_at ON regime_snapshots(recorded_at DESC);
CREATE INDEX idx_positions_ticket ON positions(ticket);

ALTER PUBLICATION supabase_realtime ADD TABLE positions, signals, bot_status;
