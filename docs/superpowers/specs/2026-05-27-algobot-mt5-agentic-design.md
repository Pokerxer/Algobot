# Algobot — MT5 Agentic Trading System

**Date:** 2026-05-27
**Status:** Design approved, awaiting implementation plan
**Owner:** jrwaldehzx@gmail.com

---

## 1. Overview

A systematic, multi-instrument trading bot for the MT5 platform (Exness broker), combining a deterministic regime-adaptive strategy engine with an AI validation layer (Claude via MCP).

The bot trades CFDs on Forex majors, Gold, and US index instruments on M15–H1 timeframes. A Python orchestrator coordinates data ingestion, regime detection, signal generation, AI validation, and order execution. State is persisted in Supabase; a Next.js dashboard provides live monitoring.

**Important framing:** No trading bot guarantees profit. This design optimizes for *robust infrastructure*: tested logic, hard risk limits, full audit trails, and graceful degradation when components fail. Profitability depends on the strategy edge, which is validated through backtesting and paper trading before any live capital is deployed.

## 2. Goals

- Trade multiple instruments on Exness MT5 systematically without manual intervention
- Detect market regimes (trending / ranging / choppy) and route to appropriate strategy
- Use an AI agent (Claude) to validate or veto high-conviction signals
- Enforce hard risk limits (per-trade, per-day, per-instrument, correlation)
- Persist all state and trade history in Supabase
- Provide a live dashboard for monitoring
- Support reproducible backtesting that shares code with live trading

## 3. Non-Goals

- Real US equities or options trading (MT5 + Exness = CFDs only)
- High-frequency trading or sub-second latency optimization
- Multi-broker support (Exness only for v1)
- Mobile app (web dashboard only)
- Auto-discovery of new strategies via ML (rule-based + AI validation in v1; ML signals are a future extension)
- Customer-facing or multi-tenant features (single user, single account)

## 4. Constraints

- **Capital:** $500 starting account
- **Platform:** MT5 desktop terminal (Windows-only for `MetaTrader5` library; bot orchestration can run elsewhere)
- **Connectivity:** All MT5 interaction routed through `metatrader-mcp-server`
- **AI cost ceiling:** AI agent invoked only for signals above a confidence threshold to keep Claude API costs proportional to account size
- **Risk budget:** Max 1% account risk per trade, 5% max daily drawdown (hard halt), max 3 concurrent positions
- **Trading window:** Day trading on M15–H1; no overnight positions held longer than 24h in v1

## 5. Tech Stack

### Python bot (`bot/`)
- Python 3.11+
- `metatrader-mcp-server` (external MCP server for MT5 connectivity)
- `mcp` (Python MCP client)
- `anthropic` (Claude SDK for AI agent)
- `supabase` (supabase-py client)
- `pandas`, `numpy`, `pandas-ta` (data + indicators)
- `pydantic` (config + signal schema validation)
- `pytest` (testing)
- `APScheduler` or `asyncio` event loop (scheduling)

### Dashboard (`dashboard/`)
- Next.js 15+ (App Router)
- `@supabase/supabase-js` (client + realtime subscriptions)
- `@supabase/ssr` (server-side auth)
- Tailwind CSS + shadcn/ui (UI primitives)
- `recharts` or `tremor` (charts)
- Deployed on Vercel

### Database (`supabase/`)
- Supabase (managed Postgres + realtime + auth)
- Schema versioned via SQL migrations

## 6. Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  MT5 Terminal (Exness)                    │
└─────────────────────────┬────────────────────────────────┘
                          │ native MT5 API
┌─────────────────────────▼────────────────────────────────┐
│              metatrader-mcp-server                        │
│  Tools: get_rates · get_symbols · account_info           │
│         place_order · close_position · get_positions      │
└─────────────────────────┬────────────────────────────────┘
                          │ MCP protocol
┌─────────────────────────▼────────────────────────────────┐
│                  Python Orchestrator                       │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Analytical Pipeline                    │ │
│  │  DataFetcher → RegimeDetector →                    │ │
│  │  InstrumentSelector → StrategyEngine → RiskManager │ │
│  └──────────────────────────┬──────────────────────────┘ │
│                             │ candidate signals           │
│  ┌──────────────────────────▼──────────────────────────┐ │
│  │              AI Agent (Claude)                      │ │
│  │  • Reviews candidate signals + regime context       │ │
│  │  • Read-only MCP tool access for additional data    │ │
│  │  • Outputs: APPROVE / VETO / MODIFY (SL/TP only)   │ │
│  │  • Fails open: falls back to rule-based approval    │ │
│  └──────────────────────────┬──────────────────────────┘ │
│                             │ approved + sized signals    │
│  ┌──────────────────────────▼──────────────────────────┐ │
│  │        ExecutionEngine (via MCP tools)              │ │
│  │        PortfolioManager · Logger                    │ │
│  └──────────────────────────┬──────────────────────────┘ │
└─────────────────────────────┼────────────────────────────┘
                              │ supabase-py
                  ┌───────────▼───────────┐
                  │       Supabase        │
                  └───────────┬───────────┘
                              │ realtime
                  ┌───────────▼───────────┐
                  │  Next.js Dashboard    │
                  └───────────────────────┘
```

### Critical invariants

1. The AI agent **cannot** directly call `place_order` or `close_position`. It can only emit APPROVE / VETO / MODIFY decisions.
2. The RiskManager is the **single source of truth** for position sizing — never bypassed.
3. If the AI agent times out or errors, the system **fails open** to rule-based approval. The bot is never blocked by the AI layer.
4. The Supabase write path is **non-blocking** to the trading loop — DB failures log but never halt trading.
5. Backtest code and live trading code share the same `RegimeDetector`, `StrategyEngine`, and `RiskManager` modules. Only `DataFetcher` and `ExecutionEngine` differ.

## 7. Components

### 7.1 DataFetcher (`bot/src/data/fetcher.py`)
- Wraps MCP `get_rates` and `get_symbols` calls
- Maintains in-memory OHLCV cache per (instrument, timeframe)
- Refreshes M15 every 15 minutes, H1 every hour
- Handles MCP connection retry with exponential backoff

### 7.2 RegimeDetector (`bot/src/regime/detector.py`)
- Input: OHLCV DataFrame for an instrument
- Computes ADX (14-period), Bollinger Band width, ATR
- Classification:
  - **TRENDING_UP**: ADX > 25, +DI > -DI
  - **TRENDING_DOWN**: ADX > 25, -DI > +DI
  - **RANGING**: ADX < 20, BB width below 30-day median
  - **CHOPPY**: ADX between 20-25, or BB width > 90th percentile (high volatility, no direction)
- Output: `RegimeState(instrument, regime, confidence: float, indicators: dict)`
- Confidence is normalized 0-1 based on how far ADX is from threshold

### 7.3 InstrumentSelector (`bot/src/selection/instrument_selector.py`)
- Scores each instrument: `score = regime_confidence × recent_sharpe_30d × (1 / spread_cost_ratio)`
- `spread_cost_ratio = spread / ATR` — filters out instruments where transaction costs eat the edge
- Selects top 3 instruments per cycle for trading (configurable, default 3)
- Updates on H1 close

### 7.4 StrategyEngine (`bot/src/strategies/`)
- Abstract `BaseStrategy` with `generate_signal(ohlcv, regime) -> Optional[Signal]`
- **MomentumStrategy** (active in TRENDING regimes):
  - 20-EMA / 50-EMA crossover for direction
  - Entry on pullback to 20-EMA with confirmation candle
  - Stop loss: 1.5 × ATR
  - Take profit: 3 × ATR (2:1 R:R)
  - Trailing stop activates at 1 × ATR profit
- **MeanReversionStrategy** (active in RANGING regimes):
  - Bollinger Bands (20, 2σ)
  - Entry on band touch + RSI confirmation (< 30 or > 70)
  - Stop loss: 1 × ATR beyond band
  - Take profit: Bollinger midline
- **NoTradeStrategy** (active in CHOPPY regimes): returns no signals

### 7.5 RiskManager (`bot/src/risk/manager.py`)
- **Position sizing:** fixed fractional, 1% account risk per trade
  - `lot_size = (account_balance × 0.01) / (stop_distance_pips × pip_value)`
- **Hard limits:**
  - Max 3 concurrent open positions
  - Max 5% daily drawdown → halt trading until next day
  - Max 2% single-trade loss (oversize check)
  - Correlation filter: reject signal if rolling 30-day correlation > 0.7 with an existing same-direction position (e.g., EURUSD long + GBPUSD long); correlation matrix refreshed daily from H1 closes
- **Spread filter:** reject signal if current spread > 2× average spread for that instrument

### 7.6 AIAgent (`bot/src/agent/claude_agent.py`)
- Triggered for signals with rule-based confidence > 0.6 (configurable)
- Uses Claude via `anthropic` SDK with tool-use enabled
- Available MCP tools (read-only subset): `get_rates`, `get_symbol_info`, `get_positions`, `account_info`
- System prompt frames Claude as a trading risk reviewer, not a trader
- Output schema (Pydantic):
  ```python
  class AIDecision(BaseModel):
      decision: Literal["APPROVE", "VETO", "MODIFY"]
      reasoning: str
      modified_sl: Optional[float] = None
      modified_tp: Optional[float] = None
      confidence: float  # 0-1
  ```
- Timeout: 30s; on timeout, fall back to rule-based approval and log
- Cost cap: max N AI calls per day (configurable, default 50)

### 7.7 ExecutionEngine (`bot/src/execution/engine.py`)
- Wraps MCP `place_order`, `close_position`, `modify_position`
- Order state machine: `PENDING → SUBMITTED → OPEN → CLOSED`
- Handles requotes, partial fills, slippage
- Persists every state transition to `signals` and `positions` tables

### 7.8 PortfolioManager (`bot/src/portfolio/manager.py`)
- Tracks open positions in memory (synced from MCP `get_positions`)
- Calculates real-time unrealized P&L
- Updates trailing stops every 1 minute
- Reports drawdown to RiskManager
- Closes positions exceeding max holding time (24h)

### 7.9 Supabase Client (`bot/src/db/supabase_client.py`)
- Thin wrapper over `supabase-py`
- Async, non-blocking writes (fire-and-forget with error logging)
- Methods: `log_signal`, `upsert_position`, `record_trade`, `update_bot_status`, `snapshot_regime`

### 7.10 Orchestrator (`bot/src/bot.py`)
- Main event loop
- Schedules H1, M15, and 1-minute jobs
- Coordinates pipeline: data → regime → selection → strategy → AI → risk → execution
- Heartbeat updates to `bot_status` every 30s
- Graceful shutdown on SIGTERM (closes MCP client, syncs final state to Supabase)

## 8. Main Loop

```
Every H1 close:
  1. Refresh OHLCV cache (M15 + H1) for all configured instruments
  2. Run RegimeDetector → per-instrument regime + confidence
  3. Snapshot regimes to Supabase
  4. InstrumentSelector ranks → picks top 3
  5. For each selected instrument: StrategyEngine generates candidate signal

Every M15 close:
  1. For each candidate signal:
     a. If confidence > AI_THRESHOLD → invoke AIAgent
     b. Else → auto-approve at rule-based confidence
  2. RiskManager sizes approved signals + applies hard limits
  3. ExecutionEngine places orders via MCP
  4. Log signal + decision to Supabase

Every 1 minute:
  1. PortfolioManager syncs open positions from MCP
  2. Update trailing stops if profit threshold met
  3. Check TP / SL hits → record trade closure
  4. Check daily drawdown → halt if breached
  5. Check max holding time → force close if exceeded
  6. Heartbeat to Supabase
```

## 9. Database Schema (Supabase)

```sql
CREATE TABLE positions (
  id BIGSERIAL PRIMARY KEY,
  ticket BIGINT UNIQUE NOT NULL,
  instrument TEXT NOT NULL,
  direction TEXT CHECK (direction IN ('BUY','SELL')),
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
  direction TEXT,
  entry_price NUMERIC,
  exit_price NUMERIC,
  volume NUMERIC,
  profit NUMERIC,
  opened_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  strategy TEXT,
  regime TEXT,
  ai_decision TEXT,
  ai_reasoning TEXT,
  duration_minutes INT
);

CREATE TABLE signals (
  id BIGSERIAL PRIMARY KEY,
  instrument TEXT,
  direction TEXT,
  confidence NUMERIC,
  regime TEXT,
  strategy TEXT,
  ai_decision TEXT,
  ai_reasoning TEXT,
  executed BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE regime_snapshots (
  id BIGSERIAL PRIMARY KEY,
  instrument TEXT,
  regime TEXT,
  adx NUMERIC,
  bb_width NUMERIC,
  confidence NUMERIC,
  recorded_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE performance_daily (
  id BIGSERIAL PRIMARY KEY,
  date DATE UNIQUE,
  total_trades INT,
  win_rate NUMERIC,
  profit NUMERIC,
  drawdown NUMERIC,
  balance NUMERIC,
  sharpe NUMERIC
);

CREATE TABLE bot_status (
  id BIGSERIAL PRIMARY KEY,
  status TEXT,
  last_heartbeat TIMESTAMPTZ,
  error_message TEXT,
  uptime_seconds INT,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_trades_closed_at ON trades(closed_at DESC);
CREATE INDEX idx_signals_created_at ON signals(created_at DESC);
CREATE INDEX idx_regime_recorded_at ON regime_snapshots(recorded_at DESC);
```

Realtime is enabled on `positions`, `signals`, `bot_status`.

## 10. Configuration (`bot/config/settings.yaml`)

```yaml
account:
  starting_balance: 500
  max_daily_drawdown_pct: 5
  max_concurrent_positions: 3
  risk_per_trade_pct: 1

instruments:
  - EURUSD
  - GBPUSD
  - USDJPY
  - XAUUSD
  - US500
  - NAS100
  - US30

timeframes:
  regime: H1
  entry: M15

regime:
  adx_period: 14
  adx_trend_threshold: 25
  adx_range_threshold: 20
  bb_period: 20
  bb_std: 2

strategy:
  momentum:
    fast_ema: 20
    slow_ema: 50
    atr_stop_multiplier: 1.5
    atr_target_multiplier: 3.0
  mean_reversion:
    rsi_period: 14
    rsi_oversold: 30
    rsi_overbought: 70

ai:
  enabled: true
  confidence_threshold: 0.6
  timeout_seconds: 30
  max_calls_per_day: 50
  model: claude-sonnet-4-6

execution:
  max_holding_hours: 24
  max_spread_multiplier: 2.0
```

## 11. Dashboard (`dashboard/`)

### Pages (Next.js App Router)
- `/` — Overview: account balance, daily P&L, bot status, open positions count
- `/positions` — Live positions table, realtime updates
- `/trades` — Trade history with filters (instrument, strategy, date range)
- `/performance` — Equity curve, drawdown chart, win rate by strategy/regime
- `/regime` — Current regime per instrument with confidence
- `/signals` — Signal log with AI decisions and reasoning

### Data flow
- Initial load: Server Components fetch via Supabase server client
- Live updates: Client Components subscribe to Supabase Realtime channels
- Auth: Supabase Auth (single-user, magic-link login)

### Dashboard is not in the first implementation sprint. It is built after the bot is running and writing to Supabase.

## 12. Testing Strategy

### Unit tests
- `RegimeDetector`: synthetic OHLCV fixtures → assert correct classification
- `StrategyEngine`: hand-crafted scenarios → assert expected signals
- `RiskManager`: edge cases (zero balance, max positions, correlation)
- `AIAgent`: mocked Claude responses → assert decision routing

### Integration tests
- Mock MCP server with deterministic responses
- Run full pipeline against fixture data
- Verify Supabase writes (against local Supabase instance)

### Backtest
- Walk-forward over 2 years of historical M15/H1 data
- Metrics: Sharpe, max drawdown, profit factor, win rate by regime
- Out-of-sample validation (last 6 months held out)

### Paper trading
- Run on Exness demo account for minimum 4 weeks before live capital
- Compare paper results to backtest expectations (regime distribution, trade frequency)

## 13. Operations

### Deployment
- Bot runs on a Windows VM (required for MT5 terminal) — VPS provider TBD
- `metatrader-mcp-server` runs as a local process alongside the bot
- Dashboard deploys to Vercel
- Supabase: managed cloud instance, free tier sufficient for v1

### Monitoring
- Bot heartbeat to `bot_status` every 30s
- Dashboard shows red status if heartbeat > 2 min old
- Optional Telegram alerts on: position open/close, drawdown breach, errors

### Secrets
- `.env` files (not committed)
- Variables: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`
- Dashboard uses `SUPABASE_ANON_KEY` (RLS-protected reads only)

## 14. Implementation Phases

### Phase 1: Core engine (no AI, no dashboard)
- DataFetcher, RegimeDetector, InstrumentSelector, StrategyEngine, RiskManager, ExecutionEngine, PortfolioManager
- Supabase schema + client
- Backtest runner
- Unit tests for all components

### Phase 2: AI integration
- AIAgent with Claude SDK + MCP tool access
- Signal validation pipeline integration
- Cost tracking and rate limiting

### Phase 3: Paper trading validation
- Deploy to demo Exness account
- 4+ weeks of monitored paper trading
- Tuning based on observed behavior

### Phase 4: Dashboard
- Next.js scaffold + Supabase auth
- Live positions, trade history, performance pages
- Deploy to Vercel

### Phase 5: Live deployment (after Phase 3 validation)
- Small live capital ($500)
- Strict adherence to risk limits
- Weekly performance review

## 15. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Strategy has no real edge | Mandatory backtest + 4-week paper trade before live capital |
| Overfitting to backtest data | Walk-forward validation, out-of-sample holdout |
| MCP server crash mid-trade | Order state machine + position reconciliation on restart |
| Claude API outage | AI layer fails open to rule-based approval |
| Supabase outage | Non-blocking writes; bot continues trading, logs locally to fallback file |
| Catastrophic loss | Hard 5% daily drawdown halt; 1% per-trade cap |
| Correlated drawdown | Correlation filter in RiskManager |
| Slippage / requotes on news | Spread filter rejects entries when spread > 2× average |
| Runaway AI execution | AI agent has no execution tools; only emits decisions |

## 16. Open Questions

- Final VPS provider for Windows MT5 host (e.g., ForexVPS, Contabo)
- Exact instrument list — may narrow after backtesting reveals which have edge
- Whether to add Telegram alerts in Phase 1 or defer to Phase 4
- ML signal layer (Approach C from brainstorming) — design hook included but implementation deferred

## 17. Success Criteria

- **Phase 1 complete:** all components covered by unit tests; backtest runs end-to-end on historical data; Sharpe > 1.0 in walk-forward
- **Phase 3 complete:** 4 weeks paper trading with drawdown < 5% and behavior matching backtest expectations
- **Phase 5 (live) complete:** 30 days live trading without breaching risk limits, regardless of profitability

Profitability is a downstream outcome of strategy edge and is not a success criterion for the *infrastructure*. The infrastructure succeeds if it executes the strategy faithfully, enforces risk limits, and provides full observability.
