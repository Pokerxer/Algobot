# Algobot Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core engine of the MT5 agentic trading bot — data ingestion through order execution, with Supabase persistence and a backtest runner — without the AI validation layer or dashboard.

**Architecture:** Modular Python orchestrator that consumes OHLCV from MT5 via `metatrader-mcp-server`, classifies market regimes (TRENDING/RANGING/CHOPPY), routes signals to per-regime strategies (momentum / mean-reversion), enforces hard risk limits, places orders through MCP, and persists everything to Supabase. Backtest and live trading share the same regime/strategy/risk modules; only data and execution layers differ.

**Tech Stack:** Python 3.11+, `uv` for env management, `mcp` (MCP client), `supabase` (supabase-py), `pandas`, `numpy`, `pandas-ta`, `pydantic`, `pydantic-settings`, `pyyaml`, `pytest`, `pytest-asyncio`, `ruff`.

---

## File Structure

```
bot/
├── pyproject.toml                   # uv-managed Python project
├── .env.example                     # secrets template
├── .gitignore
├── README.md
├── main.py                          # entry point
├── config/settings.yaml             # live config
├── src/
│   ├── config/                      # Pydantic config schema + loader
│   ├── models/                      # Signal, RegimeState, Position
│   ├── mcp_client/                  # MCP wrapper (init/call_tool/close)
│   ├── data/                        # DataFetcher + OHLCV cache
│   ├── regime/                      # indicators + RegimeDetector
│   ├── selection/                   # InstrumentSelector
│   ├── strategies/                  # BaseStrategy + momentum + mean_reversion
│   ├── risk/                        # RiskManager
│   ├── execution/                   # ExecutionEngine
│   ├── portfolio/                   # PortfolioManager
│   ├── db/                          # Supabase client
│   └── bot.py                       # orchestrator
├── backtesting/
│   ├── data_provider.py
│   ├── metrics.py
│   └── runner.py
├── supabase/
│   └── migrations/001_initial.sql
└── tests/
    ├── conftest.py
    ├── fixtures/
    └── test_*.py
```

---

## Task 1: Scaffold the Python project

**Files:**
- Create: `bot/pyproject.toml`
- Create: `bot/.gitignore`
- Create: `bot/.env.example`
- Create: `bot/README.md`

- [ ] **Step 1: Create `bot/pyproject.toml`**

```toml
[project]
name = "algobot"
version = "0.1.0"
description = "MT5 agentic trading bot — regime-adaptive multi-strategy engine"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0",
    "supabase>=2.7",
    "pandas>=2.2",
    "numpy>=1.26",
    "pandas-ta>=0.3.14b0",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "pyyaml>=6.0",
    "anyio>=4.4",
]

[project.optional-dependencies]
dev = ["pytest>=8.2", "pytest-asyncio>=0.23", "pytest-mock>=3.14", "ruff>=0.5"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py311"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src", "backtesting"]
```

- [ ] **Step 2: Create `bot/.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.env
*.db
*.log
dist/
build/
*.egg-info/
.DS_Store
```

- [ ] **Step 3: Create `bot/.env.example`**

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=
ANTHROPIC_API_KEY=
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
MCP_SERVER_COMMAND=metatrader-mcp-server
```

- [ ] **Step 4: Create `bot/README.md`**

```markdown
# Algobot — MT5 Agentic Trading Bot

See `docs/superpowers/specs/2026-05-27-algobot-mt5-agentic-design.md` for design.

## Setup

cd bot
uv venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
uv pip install -e ".[dev]"
cp .env.example .env  # fill in secrets

## Run tests

pytest
```

- [ ] **Step 5: Install and verify**

Run: `cd bot && uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"`
Expected: install succeeds.

- [ ] **Step 6: Commit**

```bash
git add bot/pyproject.toml bot/.gitignore bot/.env.example bot/README.md
git commit -m "feat(bot): scaffold Python project with uv + pytest"
```

---

## Task 2: Supabase schema migration

**Files:**
- Create: `supabase/migrations/001_initial.sql`

- [ ] **Step 1: Write the migration**

```sql
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
```

- [ ] **Step 2: Commit**

```bash
git add supabase/migrations/001_initial.sql
git commit -m "feat(db): initial Supabase schema for trades, positions, signals"
```

---

## Task 3: Config schema (Pydantic)

**Files:**
- Create: `bot/src/__init__.py` (empty), `bot/src/config/__init__.py` (empty)
- Create: `bot/src/config/schema.py`
- Create: `bot/tests/__init__.py` (empty), `bot/tests/test_config_schema.py`

- [ ] **Step 1: Create empty init files**

```bash
mkdir -p bot/src/config bot/tests
touch bot/src/__init__.py bot/src/config/__init__.py bot/tests/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_config_schema.py`**

```python
import pytest
from pydantic import ValidationError
from src.config.schema import AppConfig, AccountConfig, RegimeConfig


def test_account_config_defaults():
    cfg = AccountConfig(starting_balance=500)
    assert cfg.max_daily_drawdown_pct == 5
    assert cfg.max_concurrent_positions == 3
    assert cfg.risk_per_trade_pct == 1


def test_account_config_rejects_negative_balance():
    with pytest.raises(ValidationError):
        AccountConfig(starting_balance=-100)


def test_regime_config_defaults():
    cfg = RegimeConfig()
    assert cfg.adx_period == 14
    assert cfg.adx_trend_threshold == 25


def test_app_config_full_construction():
    cfg = AppConfig(account={"starting_balance": 500}, instruments=["EURUSD"])
    assert cfg.account.starting_balance == 500
    assert "EURUSD" in cfg.instruments
    assert cfg.timeframes.regime == "H1"
```

- [ ] **Step 3: Run test (expect FAIL)**

Run: `cd bot && pytest tests/test_config_schema.py -v`

- [ ] **Step 4: Implement `bot/src/config/schema.py`**

```python
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class AccountConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starting_balance: float = Field(gt=0)
    max_daily_drawdown_pct: float = 5
    max_concurrent_positions: int = 3
    risk_per_trade_pct: float = 1


class TimeframeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regime: Literal["M15", "H1", "H4", "D1"] = "H1"
    entry: Literal["M5", "M15", "H1"] = "M15"


class RegimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adx_period: int = 14
    adx_trend_threshold: float = 25
    adx_range_threshold: float = 20
    bb_period: int = 20
    bb_std: float = 2.0


class MomentumStrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fast_ema: int = 20
    slow_ema: int = 50
    atr_stop_multiplier: float = 1.5
    atr_target_multiplier: float = 3.0


class MeanReversionStrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rsi_period: int = 14
    rsi_oversold: float = 30
    rsi_overbought: float = 70


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    momentum: MomentumStrategyConfig = MomentumStrategyConfig()
    mean_reversion: MeanReversionStrategyConfig = MeanReversionStrategyConfig()


class AIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    confidence_threshold: float = 0.6
    timeout_seconds: int = 30
    max_calls_per_day: int = 50
    model: str = "claude-sonnet-4-6"


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_holding_hours: int = 24
    max_spread_multiplier: float = 2.0


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: AccountConfig
    instruments: list[str]
    timeframes: TimeframeConfig = TimeframeConfig()
    regime: RegimeConfig = RegimeConfig()
    strategy: StrategyConfig = StrategyConfig()
    ai: AIConfig = AIConfig()
    execution: ExecutionConfig = ExecutionConfig()
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_config_schema.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/src/__init__.py bot/src/config/ bot/tests/__init__.py bot/tests/test_config_schema.py
git commit -m "feat(config): Pydantic config schema with defaults + validation"
```

---

## Task 4: Config loader (YAML → AppConfig)

**Files:**
- Create: `bot/config/settings.yaml`
- Create: `bot/src/config/loader.py`
- Create: `bot/tests/test_config_loader.py`

- [ ] **Step 1: Create `bot/config/settings.yaml`**

```yaml
account:
  starting_balance: 500
  max_daily_drawdown_pct: 5
  max_concurrent_positions: 3
  risk_per_trade_pct: 1

instruments: [EURUSD, GBPUSD, USDJPY, XAUUSD, US500, NAS100, US30]

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
  enabled: false
  confidence_threshold: 0.6
  timeout_seconds: 30
  max_calls_per_day: 50
  model: claude-sonnet-4-6

execution:
  max_holding_hours: 24
  max_spread_multiplier: 2.0
```

- [ ] **Step 2: Write failing test `bot/tests/test_config_loader.py`**

```python
import pytest
from pathlib import Path
from src.config.loader import load_config


def test_load_default_config():
    cfg = load_config(Path("config/settings.yaml"))
    assert cfg.account.starting_balance == 500
    assert "EURUSD" in cfg.instruments
    assert cfg.regime.adx_period == 14
    assert cfg.strategy.momentum.fast_ema == 20


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yaml")
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_config_loader.py -v`

- [ ] **Step 4: Implement `bot/src/config/loader.py`**

```python
from pathlib import Path
import yaml
from src.config.schema import AppConfig


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r") as f:
        data = yaml.safe_load(f)
    return AppConfig(**data)
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_config_loader.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/config/settings.yaml bot/src/config/loader.py bot/tests/test_config_loader.py
git commit -m "feat(config): YAML loader producing validated AppConfig"
```

---

## Task 5: Domain models (Signal, RegimeState, Position)

**Files:**
- Create: `bot/src/models/__init__.py`, `signal.py`, `regime.py`, `position.py`
- Create: `bot/tests/test_models.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/models && touch bot/src/models/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_models.py`**

```python
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from src.models.signal import Signal, Direction
from src.models.regime import RegimeState, Regime
from src.models.position import Position


def test_signal_construction():
    sig = Signal(
        instrument="EURUSD", direction=Direction.BUY,
        entry_price=1.085, stop_loss=1.082, take_profit=1.091,
        confidence=0.75, regime=Regime.TRENDING_UP, strategy="momentum",
    )
    assert sig.confidence == 0.75


def test_signal_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        Signal(
            instrument="EURUSD", direction=Direction.BUY,
            entry_price=1, stop_loss=0.9, take_profit=1.1,
            confidence=1.5, regime=Regime.TRENDING_UP, strategy="momentum",
        )


def test_regime_state_construction():
    rs = RegimeState(
        instrument="XAUUSD", regime=Regime.RANGING, confidence=0.8,
        indicators={"adx": 15.2, "bb_width": 0.012},
    )
    assert rs.regime == Regime.RANGING


def test_position_construction():
    pos = Position(
        ticket=12345, instrument="EURUSD", direction=Direction.BUY,
        entry_price=1.085, volume=0.01, stop_loss=1.082, take_profit=1.091,
        opened_at=datetime.now(timezone.utc), strategy="momentum",
        regime=Regime.TRENDING_UP,
    )
    assert pos.profit == 0
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_models.py -v`

- [ ] **Step 4: Implement `bot/src/models/regime.py`**

```python
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, ConfigDict


class Regime(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    CHOPPY = "CHOPPY"


class RegimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    regime: Regime
    confidence: float = Field(ge=0, le=1)
    indicators: dict[str, Any] = {}
```

- [ ] **Step 5: Implement `bot/src/models/signal.py`**

```python
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
from src.models.regime import Regime


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    direction: Direction
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    regime: Regime
    strategy: str
```

- [ ] **Step 6: Implement `bot/src/models/position.py`**

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from src.models.signal import Direction
from src.models.regime import Regime


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: int
    instrument: str
    direction: Direction
    entry_price: float = Field(gt=0)
    current_price: Optional[float] = None
    volume: float = Field(gt=0)
    profit: float = 0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: datetime
    strategy: str
    regime: Regime
```

- [ ] **Step 7: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_models.py -v`

- [ ] **Step 8: Commit**

```bash
git add bot/src/models/ bot/tests/test_models.py
git commit -m "feat(models): Signal, RegimeState, Position Pydantic models"
```

---

## Task 6: MCP client wrapper

**Files:**
- Create: `bot/src/mcp_client/__init__.py`, `protocol.py`, `client.py`, `fake.py`
- Create: `bot/tests/test_mcp_client.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/mcp_client && touch bot/src/mcp_client/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_mcp_client.py`**

```python
import pytest
from src.mcp_client.fake import FakeMCPClient


@pytest.mark.asyncio
async def test_fake_returns_canned_response():
    client = FakeMCPClient(responses={"account_info": {"balance": 500.0}})
    assert await client.call_tool("account_info", {}) == {"balance": 500.0}


@pytest.mark.asyncio
async def test_fake_raises_on_unknown_tool():
    with pytest.raises(KeyError):
        await FakeMCPClient(responses={}).call_tool("nope", {})


@pytest.mark.asyncio
async def test_fake_records_calls():
    client = FakeMCPClient(responses={"get_rates": []})
    await client.call_tool("get_rates", {"symbol": "EURUSD"})
    assert client.calls == [("get_rates", {"symbol": "EURUSD"})]
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_mcp_client.py -v`

- [ ] **Step 4: Implement `bot/src/mcp_client/protocol.py`**

```python
from typing import Any, Protocol


class MCPClient(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...
    async def close(self) -> None: ...
```

- [ ] **Step 5: Implement `bot/src/mcp_client/fake.py`**

```python
from typing import Any


class FakeMCPClient:
    def __init__(self, responses: dict[str, Any]):
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name not in self._responses:
            raise KeyError(f"FakeMCPClient has no response for tool '{name}'")
        return self._responses[name]

    async def close(self) -> None:
        pass
```

- [ ] **Step 6: Implement `bot/src/mcp_client/client.py`**

```python
import os
import shlex
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class StdioMCPClient:
    def __init__(self, command: str | None = None):
        cmd_str = command or os.environ.get("MCP_SERVER_COMMAND", "metatrader-mcp-server")
        parts = shlex.split(cmd_str)
        self._params = StdioServerParameters(command=parts[0], args=parts[1:])
        self._session: ClientSession | None = None
        self._stdio_ctx = None
        self._session_ctx = None

    async def connect(self) -> None:
        self._stdio_ctx = stdio_client(self._params)
        read, write = await self._stdio_ctx.__aenter__()
        self._session_ctx = ClientSession(read, write)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("MCP client not connected. Call connect() first.")
        result = await self._session.call_tool(name, arguments)
        return result.content

    async def close(self) -> None:
        if self._session_ctx is not None:
            await self._session_ctx.__aexit__(None, None, None)
        if self._stdio_ctx is not None:
            await self._stdio_ctx.__aexit__(None, None, None)
```

- [ ] **Step 7: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_mcp_client.py -v`

- [ ] **Step 8: Commit**

```bash
git add bot/src/mcp_client/ bot/tests/test_mcp_client.py
git commit -m "feat(mcp): MCP client protocol + stdio impl + fake for tests"
```

---

## Task 7: OHLCV cache

**Files:**
- Create: `bot/src/data/__init__.py`, `cache.py`
- Create: `bot/tests/test_data_cache.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/data && touch bot/src/data/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_data_cache.py`**

```python
import pandas as pd
from datetime import datetime, timezone
from src.data.cache import OHLCVCache


def _make_df(n=100):
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz=timezone.utc)
    return pd.DataFrame(
        {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100}, index=idx,
    )


def test_cache_stores_and_retrieves():
    cache = OHLCVCache()
    cache.set("EURUSD", "H1", _make_df())
    assert len(cache.get("EURUSD", "H1")) == 100


def test_cache_returns_none_for_missing():
    assert OHLCVCache().get("XAUUSD", "H1") is None


def test_cache_stale_when_old():
    cache = OHLCVCache(ttl_seconds={"H1": 3600})
    cache.set("EURUSD", "H1", _make_df(),
              fetched_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert cache.is_stale("EURUSD", "H1") is True


def test_cache_fresh_when_just_set():
    cache = OHLCVCache(ttl_seconds={"H1": 3600})
    cache.set("EURUSD", "H1", _make_df())
    assert cache.is_stale("EURUSD", "H1") is False
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_data_cache.py -v`

- [ ] **Step 4: Implement `bot/src/data/cache.py`**

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import pandas as pd

DEFAULT_TTL = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}


@dataclass
class _Entry:
    df: pd.DataFrame
    fetched_at: datetime


class OHLCVCache:
    def __init__(self, ttl_seconds: Optional[dict[str, int]] = None):
        self._store: dict[tuple[str, str], _Entry] = {}
        self._ttl = ttl_seconds or DEFAULT_TTL

    def set(self, instrument: str, timeframe: str, df: pd.DataFrame,
            fetched_at: Optional[datetime] = None) -> None:
        self._store[(instrument, timeframe)] = _Entry(
            df=df.copy(), fetched_at=fetched_at or datetime.now(timezone.utc),
        )

    def get(self, instrument: str, timeframe: str) -> Optional[pd.DataFrame]:
        entry = self._store.get((instrument, timeframe))
        return None if entry is None else entry.df

    def is_stale(self, instrument: str, timeframe: str) -> bool:
        entry = self._store.get((instrument, timeframe))
        if entry is None:
            return True
        ttl = self._ttl.get(timeframe, 0)
        age = (datetime.now(timezone.utc) - entry.fetched_at).total_seconds()
        return age >= ttl
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_data_cache.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/src/data/ bot/tests/test_data_cache.py
git commit -m "feat(data): OHLCV cache with per-timeframe TTL"
```

---

## Task 8: DataFetcher (MCP-backed)

**Files:**
- Create: `bot/src/data/fetcher.py`
- Create: `bot/tests/test_data_fetcher.py`

- [ ] **Step 1: Write failing test `bot/tests/test_data_fetcher.py`**

```python
import pytest
import pandas as pd
from src.data.fetcher import DataFetcher
from src.data.cache import OHLCVCache
from src.mcp_client.fake import FakeMCPClient


def _fake_rates(n=50):
    return [
        {"time": 1704067200 + i * 3600, "open": 1.0, "high": 1.1,
         "low": 0.9, "close": 1.05, "tick_volume": 100}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_fetcher_returns_dataframe():
    mcp = FakeMCPClient(responses={"get_rates": _fake_rates(50)})
    df = await DataFetcher(mcp, OHLCVCache()).fetch_ohlcv("EURUSD", "H1", bars=50)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 50
    assert {"open", "high", "low", "close", "volume"}.issubset(df.columns)


@pytest.mark.asyncio
async def test_fetcher_uses_cache_when_fresh():
    mcp = FakeMCPClient(responses={"get_rates": _fake_rates(50)})
    fetcher = DataFetcher(mcp, OHLCVCache(ttl_seconds={"H1": 3600}))
    await fetcher.fetch_ohlcv("EURUSD", "H1", bars=50)
    await fetcher.fetch_ohlcv("EURUSD", "H1", bars=50)
    assert len(mcp.calls) == 1


@pytest.mark.asyncio
async def test_fetcher_passes_correct_arguments():
    mcp = FakeMCPClient(responses={"get_rates": _fake_rates(10)})
    await DataFetcher(mcp, OHLCVCache()).fetch_ohlcv("XAUUSD", "M15", bars=10)
    name, args = mcp.calls[0]
    assert name == "get_rates"
    assert args == {"symbol": "XAUUSD", "timeframe": "M15", "count": 10}
```

- [ ] **Step 2: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_data_fetcher.py -v`

- [ ] **Step 3: Implement `bot/src/data/fetcher.py`**

```python
from typing import Any
import pandas as pd
from src.data.cache import OHLCVCache
from src.mcp_client.protocol import MCPClient


class DataFetcher:
    def __init__(self, mcp: MCPClient, cache: OHLCVCache):
        self._mcp = mcp
        self._cache = cache

    async def fetch_ohlcv(self, instrument: str, timeframe: str,
                          bars: int = 500) -> pd.DataFrame:
        if not self._cache.is_stale(instrument, timeframe):
            cached = self._cache.get(instrument, timeframe)
            if cached is not None and len(cached) >= bars:
                return cached.tail(bars)

        raw = await self._mcp.call_tool(
            "get_rates",
            {"symbol": instrument, "timeframe": timeframe, "count": bars},
        )
        df = self._to_dataframe(raw)
        self._cache.set(instrument, timeframe, df)
        return df

    @staticmethod
    def _to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        if "tick_volume" in df.columns and "volume" not in df.columns:
            df = df.rename(columns={"tick_volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]]
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_data_fetcher.py -v`

- [ ] **Step 5: Commit**

```bash
git add bot/src/data/fetcher.py bot/tests/test_data_fetcher.py
git commit -m "feat(data): MCP-backed DataFetcher with cache-aware fetching"
```

---

## Task 9: Regime indicators (ADX, BB width, ATR)

**Files:**
- Create: `bot/src/regime/__init__.py`, `indicators.py`
- Create: `bot/tests/test_regime_indicators.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/regime && touch bot/src/regime/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_regime_indicators.py`**

```python
import numpy as np
import pandas as pd
from src.regime.indicators import compute_adx, compute_bb_width, compute_atr


def _trending(n=200):
    close = np.linspace(1.0, 1.5, n)
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def _ranging(n=200):
    rng = np.random.default_rng(42)
    close = 1.0 + 0.01 * np.sin(np.linspace(0, 20, n)) + rng.normal(0, 0.0005, n)
    return pd.DataFrame({"open": close, "high": close + 0.002,
                         "low": close - 0.002, "close": close})


def test_adx_higher_for_trending():
    trend = compute_adx(_trending(), period=14)
    rng = compute_adx(_ranging(), period=14)
    assert trend["adx"].iloc[-1] > rng["adx"].iloc[-1]


def test_adx_returns_di_components():
    out = compute_adx(_trending(), period=14)
    assert {"adx", "plus_di", "minus_di"}.issubset(out.columns)
    assert out["plus_di"].iloc[-1] > out["minus_di"].iloc[-1]


def test_bb_width_computable():
    width = compute_bb_width(_trending(), period=20, std=2.0)
    assert not width.isna().all()


def test_atr_positive():
    atr = compute_atr(_trending(), period=14)
    assert (atr.dropna() > 0).all()
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_regime_indicators.py -v`

- [ ] **Step 4: Implement `bot/src/regime/indicators.py`**

```python
import pandas as pd
import pandas_ta as ta


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    result = ta.adx(df["high"], df["low"], df["close"], length=period)
    if result is None:
        raise ValueError("ADX calculation failed")
    return result.rename(columns={
        f"ADX_{period}": "adx",
        f"DMP_{period}": "plus_di",
        f"DMN_{period}": "minus_di",
    })


def compute_bb_width(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.Series:
    bb = ta.bbands(df["close"], length=period, std=std)
    if bb is None:
        raise ValueError("Bollinger Bands calculation failed")
    upper = bb[f"BBU_{period}_{std}"]
    lower = bb[f"BBL_{period}_{std}"]
    middle = bb[f"BBM_{period}_{std}"]
    return (upper - lower) / middle


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.atr(df["high"], df["low"], df["close"], length=period)
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_regime_indicators.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/src/regime/__init__.py bot/src/regime/indicators.py bot/tests/test_regime_indicators.py
git commit -m "feat(regime): ADX, Bollinger width, ATR indicator wrappers"
```

---

## Task 10: RegimeDetector

**Files:**
- Create: `bot/src/regime/detector.py`
- Create: `bot/tests/test_regime_detector.py`

- [ ] **Step 1: Write failing test `bot/tests/test_regime_detector.py`**

```python
import numpy as np
import pandas as pd
from src.regime.detector import RegimeDetector
from src.config.schema import RegimeConfig
from src.models.regime import Regime


def _uptrend(n=200):
    close = np.linspace(1.0, 1.5, n)
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def _downtrend(n=200):
    close = np.linspace(1.5, 1.0, n)
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def _ranging(n=200):
    rng = np.random.default_rng(0)
    close = 1.0 + 0.005 * np.sin(np.linspace(0, 30, n)) + rng.normal(0, 0.0003, n)
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def test_detects_trending_up():
    rs = RegimeDetector(RegimeConfig()).classify("EURUSD", _uptrend())
    assert rs.regime == Regime.TRENDING_UP


def test_detects_trending_down():
    rs = RegimeDetector(RegimeConfig()).classify("EURUSD", _downtrend())
    assert rs.regime == Regime.TRENDING_DOWN


def test_detects_ranging_or_choppy():
    rs = RegimeDetector(RegimeConfig()).classify("EURUSD", _ranging())
    assert rs.regime in (Regime.RANGING, Regime.CHOPPY)


def test_returns_indicators_in_state():
    rs = RegimeDetector(RegimeConfig()).classify("EURUSD", _uptrend())
    assert "adx" in rs.indicators
    assert "bb_width" in rs.indicators
```

- [ ] **Step 2: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_regime_detector.py -v`

- [ ] **Step 3: Implement `bot/src/regime/detector.py`**

```python
import pandas as pd
from src.config.schema import RegimeConfig
from src.models.regime import Regime, RegimeState
from src.regime.indicators import compute_adx, compute_bb_width


class RegimeDetector:
    def __init__(self, config: RegimeConfig):
        self._cfg = config

    def classify(self, instrument: str, df: pd.DataFrame) -> RegimeState:
        adx_df = compute_adx(df, self._cfg.adx_period)
        bb_width = compute_bb_width(df, self._cfg.bb_period, self._cfg.bb_std)

        adx = float(adx_df["adx"].iloc[-1])
        plus_di = float(adx_df["plus_di"].iloc[-1])
        minus_di = float(adx_df["minus_di"].iloc[-1])
        width = float(bb_width.iloc[-1])
        width_median = float(bb_width.tail(30).median())
        width_90 = float(bb_width.quantile(0.90))

        if adx > self._cfg.adx_trend_threshold:
            regime = Regime.TRENDING_UP if plus_di > minus_di else Regime.TRENDING_DOWN
            confidence = min(1.0, (adx - self._cfg.adx_trend_threshold) / 25)
        elif adx < self._cfg.adx_range_threshold and width <= width_median:
            regime = Regime.RANGING
            confidence = min(1.0, (self._cfg.adx_range_threshold - adx) / 20)
        else:
            regime = Regime.CHOPPY
            confidence = 1.0 if width > width_90 else 0.5

        return RegimeState(
            instrument=instrument, regime=regime, confidence=confidence,
            indicators={"adx": adx, "plus_di": plus_di, "minus_di": minus_di,
                        "bb_width": width},
        )
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_regime_detector.py -v`

- [ ] **Step 5: Commit**

```bash
git add bot/src/regime/detector.py bot/tests/test_regime_detector.py
git commit -m "feat(regime): RegimeDetector classifying TRENDING/RANGING/CHOPPY"
```

---

## Task 11: InstrumentSelector

**Files:**
- Create: `bot/src/selection/__init__.py`, `instrument_selector.py`
- Create: `bot/tests/test_instrument_selector.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/selection && touch bot/src/selection/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_instrument_selector.py`**

```python
from src.selection.instrument_selector import InstrumentSelector, InstrumentScore
from src.models.regime import Regime, RegimeState


def _state(inst, regime, conf):
    return RegimeState(instrument=inst, regime=regime, confidence=conf,
                       indicators={"adx": 30})


def test_ranks_by_confidence_when_other_factors_equal():
    states = [
        _state("EURUSD", Regime.TRENDING_UP, 0.9),
        _state("GBPUSD", Regime.TRENDING_UP, 0.5),
    ]
    spread = {"EURUSD": 0.1, "GBPUSD": 0.1}
    sharpe = {"EURUSD": 1.0, "GBPUSD": 1.0}
    selected = InstrumentSelector(top_n=1).select(states, spread, sharpe)
    assert selected[0].instrument == "EURUSD"


def test_excludes_choppy_instruments():
    states = [
        _state("EURUSD", Regime.CHOPPY, 0.9),
        _state("GBPUSD", Regime.TRENDING_UP, 0.6),
    ]
    selected = InstrumentSelector(top_n=2).select(
        states, {"EURUSD": 0.1, "GBPUSD": 0.1}, {"EURUSD": 1, "GBPUSD": 1},
    )
    assert all(s.instrument != "EURUSD" for s in selected)


def test_penalizes_high_spread_cost():
    states = [
        _state("EURUSD", Regime.TRENDING_UP, 0.8),
        _state("XAUUSD", Regime.TRENDING_UP, 0.8),
    ]
    selected = InstrumentSelector(top_n=1).select(
        states, {"EURUSD": 0.05, "XAUUSD": 0.5}, {"EURUSD": 1.0, "XAUUSD": 1.0},
    )
    assert selected[0].instrument == "EURUSD"
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_instrument_selector.py -v`

- [ ] **Step 4: Implement `bot/src/selection/instrument_selector.py`**

```python
from dataclasses import dataclass
from src.models.regime import Regime, RegimeState


@dataclass
class InstrumentScore:
    instrument: str
    score: float
    regime: Regime
    confidence: float


class InstrumentSelector:
    def __init__(self, top_n: int = 3):
        self._top_n = top_n

    def select(
        self, regime_states: list[RegimeState],
        spread_ratios: dict[str, float], recent_sharpe: dict[str, float],
    ) -> list[InstrumentScore]:
        scores = []
        for rs in regime_states:
            if rs.regime == Regime.CHOPPY:
                continue
            spread = spread_ratios.get(rs.instrument, 1.0)
            sharpe = max(recent_sharpe.get(rs.instrument, 0.0), 0.0)
            score = rs.confidence * sharpe * (1.0 / max(spread, 0.001))
            scores.append(InstrumentScore(
                instrument=rs.instrument, score=score,
                regime=rs.regime, confidence=rs.confidence,
            ))
        scores.sort(key=lambda s: s.score, reverse=True)
        return scores[: self._top_n]
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_instrument_selector.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/src/selection/ bot/tests/test_instrument_selector.py
git commit -m "feat(selection): InstrumentSelector ranking by regime × sharpe × spread"
```

---

## Task 12: BaseStrategy + MomentumStrategy

**Files:**
- Create: `bot/src/strategies/__init__.py`, `base.py`, `momentum.py`
- Create: `bot/tests/test_momentum_strategy.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/strategies && touch bot/src/strategies/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_momentum_strategy.py`**

```python
import numpy as np
import pandas as pd
from src.strategies.momentum import MomentumStrategy
from src.config.schema import MomentumStrategyConfig
from src.models.regime import Regime, RegimeState


def _uptrend_with_pullback(n=200):
    close = np.linspace(1.0, 1.2, n)
    close[-1] = close[-5]  # pullback
    return pd.DataFrame({"open": close, "high": close + 0.001,
                         "low": close - 0.001, "close": close})


def test_no_signal_in_ranging_regime():
    strat = MomentumStrategy(MomentumStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.RANGING, confidence=0.7)
    assert strat.generate_signal(_uptrend_with_pullback(), rs) is None


def test_emits_buy_with_2to1_rr_in_uptrend():
    strat = MomentumStrategy(MomentumStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.TRENDING_UP, confidence=0.8)
    sig = strat.generate_signal(_uptrend_with_pullback(), rs)
    if sig is not None:
        assert sig.direction.value == "BUY"
        r = sig.entry_price - sig.stop_loss
        rr = sig.take_profit - sig.entry_price
        assert abs(rr / r - 2.0) < 0.1
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_momentum_strategy.py -v`

- [ ] **Step 4: Implement `bot/src/strategies/base.py`**

```python
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd
from src.models.regime import RegimeState
from src.models.signal import Signal


class BaseStrategy(ABC):
    name: str

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]: ...
```

- [ ] **Step 5: Implement `bot/src/strategies/momentum.py`**

```python
from typing import Optional
import pandas as pd
import pandas_ta as ta
from src.config.schema import MomentumStrategyConfig
from src.models.regime import Regime, RegimeState
from src.models.signal import Direction, Signal
from src.regime.indicators import compute_atr
from src.strategies.base import BaseStrategy


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def __init__(self, config: MomentumStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if regime.regime not in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
            return None

        fast = ta.ema(df["close"], length=self._cfg.fast_ema)
        slow = ta.ema(df["close"], length=self._cfg.slow_ema)
        atr = compute_atr(df, period=14)
        if fast is None or slow is None or atr is None:
            return None
        if fast.isna().iloc[-1] or slow.isna().iloc[-1] or atr.isna().iloc[-1]:
            return None

        close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        fast_now = float(fast.iloc[-1])
        slow_now = float(slow.iloc[-1])
        atr_now = float(atr.iloc[-1])

        if regime.regime == Regime.TRENDING_UP and fast_now > slow_now:
            touched = float(df["low"].iloc[-2]) <= fast_now * 1.002
            bouncing = close > prev_close
            if touched and bouncing:
                stop = close - self._cfg.atr_stop_multiplier * atr_now
                target = close + self._cfg.atr_target_multiplier * atr_now
                return Signal(
                    instrument=regime.instrument, direction=Direction.BUY,
                    entry_price=close, stop_loss=stop, take_profit=target,
                    confidence=regime.confidence, regime=regime.regime, strategy=self.name,
                )

        if regime.regime == Regime.TRENDING_DOWN and fast_now < slow_now:
            touched = float(df["high"].iloc[-2]) >= fast_now * 0.998
            bouncing = close < prev_close
            if touched and bouncing:
                stop = close + self._cfg.atr_stop_multiplier * atr_now
                target = close - self._cfg.atr_target_multiplier * atr_now
                return Signal(
                    instrument=regime.instrument, direction=Direction.SELL,
                    entry_price=close, stop_loss=stop, take_profit=target,
                    confidence=regime.confidence, regime=regime.regime, strategy=self.name,
                )

        return None
```

- [ ] **Step 6: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_momentum_strategy.py -v`

- [ ] **Step 7: Commit**

```bash
git add bot/src/strategies/ bot/tests/test_momentum_strategy.py
git commit -m "feat(strategies): BaseStrategy + MomentumStrategy (EMA pullback)"
```

---

## Task 13: MeanReversionStrategy

**Files:**
- Create: `bot/src/strategies/mean_reversion.py`
- Create: `bot/tests/test_mean_reversion_strategy.py`

- [ ] **Step 1: Write failing test `bot/tests/test_mean_reversion_strategy.py`**

```python
import numpy as np
import pandas as pd
from src.strategies.mean_reversion import MeanReversionStrategy
from src.config.schema import MeanReversionStrategyConfig
from src.models.regime import Regime, RegimeState


def _ranging_with_dip(n=200):
    rng = np.random.default_rng(7)
    close = 1.0 + 0.005 * np.sin(np.linspace(0, 20, n)) + rng.normal(0, 0.0002, n)
    close[-10:] = np.linspace(close[-11], close[-11] - 0.02, 10)
    return pd.DataFrame({"open": close, "high": close + 0.0005,
                         "low": close - 0.0005, "close": close})


def test_skips_trending_regime():
    strat = MeanReversionStrategy(MeanReversionStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.TRENDING_UP, confidence=0.8)
    assert strat.generate_signal(_ranging_with_dip(), rs) is None


def test_buys_on_oversold_lower_band():
    strat = MeanReversionStrategy(MeanReversionStrategyConfig())
    rs = RegimeState(instrument="EURUSD", regime=Regime.RANGING, confidence=0.7)
    sig = strat.generate_signal(_ranging_with_dip(), rs)
    assert sig is not None
    assert sig.direction.value == "BUY"
    assert sig.stop_loss < sig.entry_price
```

- [ ] **Step 2: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_mean_reversion_strategy.py -v`

- [ ] **Step 3: Implement `bot/src/strategies/mean_reversion.py`**

```python
from typing import Optional
import pandas as pd
import pandas_ta as ta
from src.config.schema import MeanReversionStrategyConfig
from src.models.regime import Regime, RegimeState
from src.models.signal import Direction, Signal
from src.regime.indicators import compute_atr
from src.strategies.base import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def __init__(self, config: MeanReversionStrategyConfig):
        self._cfg = config

    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]:
        if regime.regime != Regime.RANGING:
            return None

        rsi = ta.rsi(df["close"], length=self._cfg.rsi_period)
        bb = ta.bbands(df["close"], length=20, std=2.0)
        atr = compute_atr(df, period=14)
        if rsi is None or bb is None or atr is None:
            return None
        if rsi.isna().iloc[-1] or atr.isna().iloc[-1]:
            return None

        close = float(df["close"].iloc[-1])
        lower = float(bb["BBL_20_2.0"].iloc[-1])
        upper = float(bb["BBU_20_2.0"].iloc[-1])
        middle = float(bb["BBM_20_2.0"].iloc[-1])
        rsi_now = float(rsi.iloc[-1])
        atr_now = float(atr.iloc[-1])

        if close <= lower and rsi_now < self._cfg.rsi_oversold:
            return Signal(
                instrument=regime.instrument, direction=Direction.BUY,
                entry_price=close, stop_loss=lower - atr_now, take_profit=middle,
                confidence=regime.confidence, regime=regime.regime, strategy=self.name,
            )

        if close >= upper and rsi_now > self._cfg.rsi_overbought:
            return Signal(
                instrument=regime.instrument, direction=Direction.SELL,
                entry_price=close, stop_loss=upper + atr_now, take_profit=middle,
                confidence=regime.confidence, regime=regime.regime, strategy=self.name,
            )

        return None
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_mean_reversion_strategy.py -v`

- [ ] **Step 5: Commit**

```bash
git add bot/src/strategies/mean_reversion.py bot/tests/test_mean_reversion_strategy.py
git commit -m "feat(strategies): MeanReversionStrategy (BB + RSI extremes)"
```

---

## Task 14: RiskManager

**Files:**
- Create: `bot/src/risk/__init__.py`, `manager.py`
- Create: `bot/tests/test_risk_manager.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/risk && touch bot/src/risk/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_risk_manager.py`**

```python
from datetime import datetime, timezone
from src.risk.manager import RiskManager
from src.config.schema import AccountConfig
from src.models.signal import Signal, Direction
from src.models.regime import Regime
from src.models.position import Position


def _sig(inst="EURUSD", entry=1.085, stop=1.082, tp=1.091, direction=Direction.BUY):
    return Signal(instrument=inst, direction=direction, entry_price=entry,
                  stop_loss=stop, take_profit=tp, confidence=0.7,
                  regime=Regime.TRENDING_UP, strategy="momentum")


def _pos(inst="EURUSD", direction=Direction.BUY):
    return Position(ticket=1, instrument=inst, direction=direction,
                    entry_price=1.085, volume=0.01,
                    opened_at=datetime.now(timezone.utc),
                    strategy="momentum", regime=Regime.TRENDING_UP)


def test_sizing_one_percent_risk():
    rm = RiskManager(AccountConfig(starting_balance=10000), pip_value=10)
    d = rm.evaluate(signal=_sig(entry=1.085, stop=1.082), balance=10000,
                    open_positions=[], daily_pnl=0,
                    correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is True
    assert abs(d.lot_size - 0.33) < 0.01


def test_rejects_at_max_positions():
    rm = RiskManager(AccountConfig(starting_balance=500, max_concurrent_positions=3))
    d = rm.evaluate(signal=_sig("EURUSD"), balance=500,
                    open_positions=[_pos("GBPUSD"), _pos("USDJPY"), _pos("XAUUSD")],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is False
    assert "concurrent" in d.reason.lower()


def test_rejects_when_drawdown_breached():
    rm = RiskManager(AccountConfig(starting_balance=500, max_daily_drawdown_pct=5))
    d = rm.evaluate(signal=_sig(), balance=475, open_positions=[],
                    daily_pnl=-30, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is False
    assert "drawdown" in d.reason.lower()


def test_rejects_wide_spread():
    rm = RiskManager(AccountConfig(starting_balance=500))
    d = rm.evaluate(signal=_sig(), balance=500, open_positions=[],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=2.5)
    assert d.approved is False
    assert "spread" in d.reason.lower()


def test_rejects_correlated_same_direction():
    rm = RiskManager(AccountConfig(starting_balance=500))
    d = rm.evaluate(signal=_sig("EURUSD", direction=Direction.BUY), balance=500,
                    open_positions=[_pos("GBPUSD", direction=Direction.BUY)],
                    daily_pnl=0,
                    correlation_matrix={("EURUSD", "GBPUSD"): 0.85},
                    spread_ratio=0.1)
    assert d.approved is False


def test_approves_correlated_opposite_direction():
    rm = RiskManager(AccountConfig(starting_balance=500))
    d = rm.evaluate(signal=_sig("EURUSD", direction=Direction.BUY), balance=500,
                    open_positions=[_pos("GBPUSD", direction=Direction.SELL)],
                    daily_pnl=0,
                    correlation_matrix={("EURUSD", "GBPUSD"): 0.85},
                    spread_ratio=0.1)
    assert d.approved is True
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_risk_manager.py -v`

- [ ] **Step 4: Implement `bot/src/risk/manager.py`**

```python
from dataclasses import dataclass
from typing import Optional
from src.config.schema import AccountConfig
from src.models.position import Position
from src.models.signal import Signal


@dataclass
class RiskDecision:
    approved: bool
    lot_size: float = 0.0
    reason: str = ""


class RiskManager:
    CORRELATION_THRESHOLD = 0.7
    MAX_SPREAD_MULTIPLIER = 2.0

    def __init__(self, config: AccountConfig, pip_value: float = 10.0):
        self._cfg = config
        self._pip_value = pip_value

    def evaluate(self, signal: Signal, balance: float,
                 open_positions: list[Position], daily_pnl: float,
                 correlation_matrix: dict[tuple[str, str], float],
                 spread_ratio: float) -> RiskDecision:
        if len(open_positions) >= self._cfg.max_concurrent_positions:
            return RiskDecision(False, reason="Max concurrent positions reached")

        max_dd = balance * (self._cfg.max_daily_drawdown_pct / 100)
        if daily_pnl <= -max_dd:
            return RiskDecision(False, reason=f"Daily drawdown breached ({daily_pnl})")

        if spread_ratio > self.MAX_SPREAD_MULTIPLIER:
            return RiskDecision(False, reason=f"Spread too wide ({spread_ratio:.2f}x)")

        for pos in open_positions:
            if pos.instrument == signal.instrument:
                return RiskDecision(False, reason="Already have position in this instrument")
            corr = self._lookup_correlation(correlation_matrix, signal.instrument, pos.instrument)
            if corr is not None and corr > self.CORRELATION_THRESHOLD and pos.direction == signal.direction:
                return RiskDecision(False, reason=f"Correlated position open (corr={corr:.2f})")

        risk_amount = balance * (self._cfg.risk_per_trade_pct / 100)
        stop_distance = abs(signal.entry_price - signal.stop_loss)
        if stop_distance <= 0:
            return RiskDecision(False, reason="Invalid stop distance")
        pip_distance = stop_distance * 10000
        lot_size = round(risk_amount / (pip_distance * self._pip_value), 2)
        if lot_size < 0.01:
            return RiskDecision(False, reason="Lot size below broker minimum")

        return RiskDecision(approved=True, lot_size=lot_size, reason="OK")

    @staticmethod
    def _lookup_correlation(matrix, a, b) -> Optional[float]:
        return matrix.get((a, b)) or matrix.get((b, a))
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_risk_manager.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/src/risk/ bot/tests/test_risk_manager.py
git commit -m "feat(risk): RiskManager with sizing + concurrent/DD/spread/correlation gates"
```

---

## Task 15: ExecutionEngine

**Files:**
- Create: `bot/src/execution/__init__.py`, `engine.py`
- Create: `bot/tests/test_execution_engine.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/execution && touch bot/src/execution/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_execution_engine.py`**

```python
import pytest
from src.execution.engine import ExecutionEngine, OrderResult
from src.mcp_client.fake import FakeMCPClient
from src.models.signal import Signal, Direction
from src.models.regime import Regime


def _sig():
    return Signal(instrument="EURUSD", direction=Direction.BUY,
                  entry_price=1.085, stop_loss=1.082, take_profit=1.091,
                  confidence=0.8, regime=Regime.TRENDING_UP, strategy="momentum")


@pytest.mark.asyncio
async def test_places_market_order():
    mcp = FakeMCPClient(responses={"place_order": {"ticket": 42,
                                                    "filled_price": 1.0851,
                                                    "status": "FILLED"}})
    result = await ExecutionEngine(mcp).place_order(_sig(), lot_size=0.05)
    assert isinstance(result, OrderResult)
    assert result.ticket == 42
    name, args = mcp.calls[0]
    assert name == "place_order"
    assert args["symbol"] == "EURUSD"
    assert args["volume"] == 0.05


@pytest.mark.asyncio
async def test_close_position():
    mcp = FakeMCPClient(responses={"close_position": {"closed": True}})
    await ExecutionEngine(mcp).close_position(ticket=42)
    assert mcp.calls[0] == ("close_position", {"ticket": 42})


@pytest.mark.asyncio
async def test_returns_rejected_on_failure_payload():
    mcp = FakeMCPClient(responses={"place_order": {"status": "REJECTED",
                                                    "error": "insufficient margin"}})
    result = await ExecutionEngine(mcp).place_order(_sig(), lot_size=0.05)
    assert result.status == "REJECTED"
    assert "margin" in (result.error or "")
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_execution_engine.py -v`

- [ ] **Step 4: Implement `bot/src/execution/engine.py`**

```python
from dataclasses import dataclass
from typing import Optional
from src.mcp_client.protocol import MCPClient
from src.models.signal import Signal


@dataclass
class OrderResult:
    ticket: Optional[int]
    filled_price: Optional[float]
    status: str
    error: Optional[str] = None


class ExecutionEngine:
    def __init__(self, mcp: MCPClient):
        self._mcp = mcp

    async def place_order(self, signal: Signal, lot_size: float) -> OrderResult:
        response = await self._mcp.call_tool("place_order", {
            "symbol": signal.instrument,
            "side": signal.direction.value,
            "volume": lot_size,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "type": "MARKET",
        })
        return OrderResult(
            ticket=response.get("ticket"),
            filled_price=response.get("filled_price"),
            status=response.get("status", "PENDING"),
            error=response.get("error"),
        )

    async def close_position(self, ticket: int) -> dict:
        return await self._mcp.call_tool("close_position", {"ticket": ticket})

    async def modify_position(self, ticket: int, stop_loss: Optional[float] = None,
                              take_profit: Optional[float] = None) -> dict:
        args: dict = {"ticket": ticket}
        if stop_loss is not None:
            args["stop_loss"] = stop_loss
        if take_profit is not None:
            args["take_profit"] = take_profit
        return await self._mcp.call_tool("modify_position", args)
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_execution_engine.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/src/execution/ bot/tests/test_execution_engine.py
git commit -m "feat(execution): ExecutionEngine wrapping place/close/modify via MCP"
```

---

## Task 16: PortfolioManager

**Files:**
- Create: `bot/src/portfolio/__init__.py`, `manager.py`
- Create: `bot/tests/test_portfolio_manager.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/portfolio && touch bot/src/portfolio/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_portfolio_manager.py`**

```python
import pytest
from datetime import datetime, timedelta, timezone
from src.portfolio.manager import PortfolioManager
from src.mcp_client.fake import FakeMCPClient
from src.models.position import Position
from src.models.signal import Direction
from src.models.regime import Regime


def _mcp_pos(ticket=1, profit=10):
    return {"ticket": ticket, "symbol": "EURUSD", "type": "BUY",
            "open_price": 1.085, "current_price": 1.087, "volume": 0.1,
            "profit": profit, "stop_loss": 1.082, "take_profit": 1.091,
            "time": int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())}


@pytest.mark.asyncio
async def test_sync_loads_positions():
    mcp = FakeMCPClient(responses={"get_positions": [_mcp_pos()]})
    pm = PortfolioManager(mcp)
    await pm.sync()
    assert pm.positions[0].ticket == 1


@pytest.mark.asyncio
async def test_total_unrealized_pnl():
    mcp = FakeMCPClient(responses={"get_positions": [
        _mcp_pos(ticket=1, profit=20), _mcp_pos(ticket=2, profit=-5),
    ]})
    pm = PortfolioManager(mcp)
    await pm.sync()
    assert pm.unrealized_pnl() == 15


def test_positions_exceeding_holding_time():
    pm = PortfolioManager(FakeMCPClient(responses={}))
    old = Position(ticket=1, instrument="EURUSD", direction=Direction.BUY,
                   entry_price=1.085, volume=0.01,
                   opened_at=datetime.now(timezone.utc) - timedelta(hours=25),
                   strategy="momentum", regime=Regime.TRENDING_UP)
    fresh = Position(ticket=2, instrument="EURUSD", direction=Direction.BUY,
                     entry_price=1.085, volume=0.01,
                     opened_at=datetime.now(timezone.utc),
                     strategy="momentum", regime=Regime.TRENDING_UP)
    pm._positions = [old, fresh]
    expired = pm.positions_exceeding_holding_time(max_hours=24)
    assert [p.ticket for p in expired] == [1]
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_portfolio_manager.py -v`

- [ ] **Step 4: Implement `bot/src/portfolio/manager.py`**

```python
from datetime import datetime, timedelta, timezone
from src.mcp_client.protocol import MCPClient
from src.models.position import Position
from src.models.signal import Direction
from src.models.regime import Regime


class PortfolioManager:
    def __init__(self, mcp: MCPClient):
        self._mcp = mcp
        self._positions: list[Position] = []

    @property
    def positions(self) -> list[Position]:
        return list(self._positions)

    async def sync(self) -> None:
        raw = await self._mcp.call_tool("get_positions", {})
        self._positions = [self._from_mcp(r) for r in raw]

    def unrealized_pnl(self) -> float:
        return sum(p.profit for p in self._positions)

    def positions_exceeding_holding_time(self, max_hours: int) -> list[Position]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
        return [p for p in self._positions if p.opened_at < cutoff]

    @staticmethod
    def _from_mcp(row: dict) -> Position:
        return Position(
            ticket=row["ticket"], instrument=row["symbol"],
            direction=Direction(row["type"]),
            entry_price=row["open_price"],
            current_price=row.get("current_price"),
            volume=row["volume"], profit=row.get("profit", 0),
            stop_loss=row.get("stop_loss"), take_profit=row.get("take_profit"),
            opened_at=datetime.fromtimestamp(row["time"], tz=timezone.utc),
            strategy=row.get("strategy", "unknown"),
            regime=Regime(row.get("regime", "TRENDING_UP")),
        )
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_portfolio_manager.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/src/portfolio/ bot/tests/test_portfolio_manager.py
git commit -m "feat(portfolio): PortfolioManager syncing positions + P&L via MCP"
```

---

## Task 17: Supabase logger

**Files:**
- Create: `bot/src/db/__init__.py`, `supabase_client.py`
- Create: `bot/tests/test_supabase_client.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p bot/src/db && touch bot/src/db/__init__.py
```

- [ ] **Step 2: Write failing test `bot/tests/test_supabase_client.py`**

```python
from unittest.mock import MagicMock
from src.db.supabase_client import SupabaseLogger
from src.models.signal import Signal, Direction
from src.models.regime import Regime


def _fake_client():
    client = MagicMock()
    chain = MagicMock()
    client.table.return_value = chain
    chain.insert.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
    chain.upsert.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
    return client, chain


def test_log_signal_inserts_into_signals_table():
    client, chain = _fake_client()
    SupabaseLogger(client).log_signal(
        Signal(instrument="EURUSD", direction=Direction.BUY,
               entry_price=1.085, stop_loss=1.082, take_profit=1.091,
               confidence=0.7, regime=Regime.TRENDING_UP, strategy="momentum"),
        executed=True,
    )
    client.table.assert_called_with("signals")
    payload = chain.insert.call_args[0][0]
    assert payload["instrument"] == "EURUSD"
    assert payload["executed"] is True


def test_update_bot_status_upserts():
    client, chain = _fake_client()
    SupabaseLogger(client).update_bot_status(status="OK", error=None)
    client.table.assert_called_with("bot_status")
    chain.upsert.assert_called_once()


def test_failures_swallowed_not_raised(caplog):
    client = MagicMock()
    client.table.side_effect = RuntimeError("network down")
    SupabaseLogger(client).update_bot_status(status="ERROR", error="x")
    assert "Supabase write failed" in caplog.text
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_supabase_client.py -v`

- [ ] **Step 4: Implement `bot/src/db/supabase_client.py`**

```python
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from src.models.position import Position
from src.models.regime import RegimeState
from src.models.signal import Signal

log = logging.getLogger(__name__)


class SupabaseLogger:
    def __init__(self, client: Any):
        self._client = client

    def log_signal(self, signal: Signal, executed: bool,
                   ai_decision: Optional[str] = None,
                   ai_reasoning: Optional[str] = None) -> None:
        self._safe_insert("signals", {
            "instrument": signal.instrument,
            "direction": signal.direction.value,
            "confidence": signal.confidence,
            "regime": signal.regime.value,
            "strategy": signal.strategy,
            "ai_decision": ai_decision,
            "ai_reasoning": ai_reasoning,
            "executed": executed,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    def upsert_position(self, position: Position) -> None:
        self._safe_upsert("positions", {
            "ticket": position.ticket,
            "instrument": position.instrument,
            "direction": position.direction.value,
            "entry_price": position.entry_price,
            "current_price": position.current_price,
            "volume": position.volume,
            "profit": position.profit,
            "stop_loss": position.stop_loss,
            "take_profit": position.take_profit,
            "opened_at": position.opened_at.isoformat(),
            "strategy": position.strategy,
            "regime": position.regime.value,
        }, on_conflict="ticket")

    def record_trade(self, **fields: Any) -> None:
        self._safe_insert("trades", fields)

    def snapshot_regime(self, state: RegimeState) -> None:
        self._safe_insert("regime_snapshots", {
            "instrument": state.instrument,
            "regime": state.regime.value,
            "adx": state.indicators.get("adx"),
            "bb_width": state.indicators.get("bb_width"),
            "confidence": state.confidence,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })

    def update_bot_status(self, status: str, error: Optional[str] = None,
                          uptime: Optional[int] = None) -> None:
        try:
            self._client.table("bot_status").upsert({
                "id": 1,
                "status": status,
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                "error_message": error,
                "uptime_seconds": uptime,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            log.warning(f"Supabase write failed (bot_status): {e}")

    def _safe_insert(self, table: str, payload: dict) -> None:
        try:
            self._client.table(table).insert(payload).execute()
        except Exception as e:
            log.warning(f"Supabase write failed ({table}): {e}")

    def _safe_upsert(self, table: str, payload: dict, on_conflict: str = "id") -> None:
        try:
            self._client.table(table).upsert(payload, on_conflict=on_conflict).execute()
        except Exception as e:
            log.warning(f"Supabase write failed ({table}): {e}")
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_supabase_client.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/src/db/ bot/tests/test_supabase_client.py
git commit -m "feat(db): SupabaseLogger with non-blocking writes"
```

---

## Task 18: Backtest data provider

**Files:**
- Create: `bot/backtesting/__init__.py`, `data_provider.py`
- Create: `bot/tests/fixtures/sample_ohlcv.csv`
- Create: `bot/tests/test_backtest_data_provider.py`

- [ ] **Step 1: Create directories**

```bash
mkdir -p bot/backtesting bot/tests/fixtures
touch bot/backtesting/__init__.py
```

- [ ] **Step 2: Create `bot/tests/fixtures/sample_ohlcv.csv`**

```csv
time,open,high,low,close,volume
2024-01-01T00:00:00Z,1.1000,1.1010,1.0990,1.1005,1000
2024-01-01T01:00:00Z,1.1005,1.1020,1.1000,1.1015,1100
2024-01-01T02:00:00Z,1.1015,1.1025,1.1010,1.1020,1200
2024-01-01T03:00:00Z,1.1020,1.1030,1.1015,1.1025,1300
2024-01-01T04:00:00Z,1.1025,1.1035,1.1020,1.1030,1400
```

- [ ] **Step 3: Write failing test `bot/tests/test_backtest_data_provider.py`**

```python
from pathlib import Path
import pandas as pd
from backtesting.data_provider import CSVDataProvider


def test_loads_ohlcv():
    provider = CSVDataProvider(Path("tests/fixtures"))
    df = provider.load("sample_ohlcv", timeframe="H1")
    assert isinstance(df, pd.DataFrame)
    assert {"open", "high", "low", "close", "volume"}.issubset(df.columns)
    assert len(df) == 5


def test_filters_by_date_range():
    provider = CSVDataProvider(Path("tests/fixtures"))
    df = provider.load("sample_ohlcv", timeframe="H1",
                       start="2024-01-01T02:00:00Z", end="2024-01-01T03:00:00Z")
    assert len(df) == 2
```

- [ ] **Step 4: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_backtest_data_provider.py -v`

- [ ] **Step 5: Implement `bot/backtesting/data_provider.py`**

```python
from pathlib import Path
from typing import Optional
import pandas as pd


class CSVDataProvider:
    def __init__(self, directory: Path):
        self._dir = directory

    def load(self, instrument: str, timeframe: str = "H1",
             start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        path = self._dir / f"{instrument}.csv"
        df = pd.read_csv(path)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        return df[["open", "high", "low", "close", "volume"]]
```

- [ ] **Step 6: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_backtest_data_provider.py -v`

- [ ] **Step 7: Commit**

```bash
git add bot/backtesting/__init__.py bot/backtesting/data_provider.py bot/tests/fixtures/sample_ohlcv.csv bot/tests/test_backtest_data_provider.py
git commit -m "feat(backtest): CSVDataProvider for historical OHLCV"
```

---

## Task 19: Backtest metrics

**Files:**
- Create: `bot/backtesting/metrics.py`
- Create: `bot/tests/test_backtest_metrics.py`

- [ ] **Step 1: Write failing test `bot/tests/test_backtest_metrics.py`**

```python
import pandas as pd
from backtesting.metrics import sharpe_ratio, max_drawdown, profit_factor, win_rate


def test_sharpe_zero_for_zero_variance():
    assert sharpe_ratio(pd.Series([0, 0, 0, 0])) == 0


def test_sharpe_positive_for_positive_returns():
    assert sharpe_ratio(pd.Series([0.01, 0.02, 0.01, 0.015])) > 0


def test_max_drawdown_simple_case():
    equity = pd.Series([100, 110, 105, 90, 95, 120])
    assert abs(max_drawdown(equity) - 0.1818) < 0.01


def test_profit_factor():
    assert abs(profit_factor(pd.Series([10, -5, 8, -3, 12])) - 3.75) < 0.01


def test_profit_factor_no_losses():
    assert profit_factor(pd.Series([10, 5, 8])) == float("inf")


def test_win_rate():
    assert win_rate(pd.Series([10, -5, 8, -3, 12])) == 0.6
```

- [ ] **Step 2: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_backtest_metrics.py -v`

- [ ] **Step 3: Implement `bot/backtesting/metrics.py`**

```python
import numpy as np
import pandas as pd


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    if returns.std() == 0 or len(returns) == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * returns.mean() / returns.std())


def max_drawdown(equity: pd.Series) -> float:
    if len(equity) == 0:
        return 0.0
    running_max = equity.cummax()
    drawdowns = (running_max - equity) / running_max
    return float(drawdowns.max())


def profit_factor(pnls: pd.Series) -> float:
    gross_profit = pnls[pnls > 0].sum()
    gross_loss = abs(pnls[pnls < 0].sum())
    if gross_loss == 0:
        return float("inf")
    return float(gross_profit / gross_loss)


def win_rate(pnls: pd.Series) -> float:
    if len(pnls) == 0:
        return 0.0
    return float((pnls > 0).sum() / len(pnls))
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_backtest_metrics.py -v`

- [ ] **Step 5: Commit**

```bash
git add bot/backtesting/metrics.py bot/tests/test_backtest_metrics.py
git commit -m "feat(backtest): Sharpe, max drawdown, profit factor, win rate metrics"
```

---

## Task 20: Backtest runner (end-to-end)

**Files:**
- Create: `bot/backtesting/runner.py`
- Create: `bot/tests/fixtures/EURUSD.csv` (synthetic data)
- Create: `bot/tests/test_backtest_runner.py`

- [ ] **Step 1: Generate `bot/tests/fixtures/EURUSD.csv`**

Run (from `bot/`):
```bash
python -c "
import pandas as pd, numpy as np
rng = np.random.default_rng(0)
n = 1000
close = 1.1 + np.cumsum(rng.normal(0, 0.0008, n))
high = close + np.abs(rng.normal(0.0005, 0.0002, n))
low = close - np.abs(rng.normal(0.0005, 0.0002, n))
open_ = close + rng.normal(0, 0.0002, n)
idx = pd.date_range('2024-01-01', periods=n, freq='h', tz='UTC')
df = pd.DataFrame({'time': idx, 'open': open_, 'high': high, 'low': low, 'close': close, 'volume': rng.integers(500, 2000, n)})
df.to_csv('tests/fixtures/EURUSD.csv', index=False)
"
```

- [ ] **Step 2: Write failing test `bot/tests/test_backtest_runner.py`**

```python
from pathlib import Path
from backtesting.runner import BacktestRunner, BacktestResult
from backtesting.data_provider import CSVDataProvider
from src.config.schema import AppConfig


def test_backtest_runs_end_to_end():
    cfg = AppConfig(account={"starting_balance": 10000}, instruments=["EURUSD"])
    runner = BacktestRunner(cfg, CSVDataProvider(Path("tests/fixtures")))
    result = runner.run(instrument="EURUSD", timeframe="H1")
    assert isinstance(result, BacktestResult)
    assert result.final_balance > 0
    assert "sharpe" in result.metrics
    assert "max_drawdown" in result.metrics
    assert "profit_factor" in result.metrics
    assert "win_rate" in result.metrics


def test_backtest_with_no_signals():
    cfg = AppConfig(
        account={"starting_balance": 1000}, instruments=["EURUSD"],
        regime={"adx_trend_threshold": 100, "adx_range_threshold": 0},
    )
    result = BacktestRunner(cfg, CSVDataProvider(Path("tests/fixtures"))).run(
        instrument="EURUSD", timeframe="H1",
    )
    assert result.final_balance == 1000
    assert len(result.trades) == 0
```

- [ ] **Step 3: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_backtest_runner.py -v`

- [ ] **Step 4: Implement `bot/backtesting/runner.py`**

```python
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
from backtesting.data_provider import CSVDataProvider
from backtesting.metrics import sharpe_ratio, max_drawdown, profit_factor, win_rate
from src.config.schema import AppConfig
from src.models.regime import Regime
from src.regime.detector import RegimeDetector
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy


@dataclass
class BacktestTrade:
    instrument: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    pnl: float
    strategy: str
    regime: str


@dataclass
class BacktestResult:
    final_balance: float
    trades: list[BacktestTrade]
    equity_curve: pd.Series
    metrics: dict[str, float] = field(default_factory=dict)


class BacktestRunner:
    MIN_BARS_FOR_REGIME = 100

    def __init__(self, config: AppConfig, data_provider: CSVDataProvider):
        self._cfg = config
        self._dp = data_provider
        self._regime = RegimeDetector(config.regime)
        self._strategies: dict[Regime, BaseStrategy] = {
            Regime.TRENDING_UP: MomentumStrategy(config.strategy.momentum),
            Regime.TRENDING_DOWN: MomentumStrategy(config.strategy.momentum),
            Regime.RANGING: MeanReversionStrategy(config.strategy.mean_reversion),
        }
        self._risk = RiskManager(config.account)

    def run(self, instrument: str, timeframe: str = "H1",
            start: Optional[str] = None, end: Optional[str] = None) -> BacktestResult:
        df = self._dp.load(instrument, timeframe, start, end)
        balance = self._cfg.account.starting_balance
        trades: list[BacktestTrade] = []
        equity = [balance]
        open_trade: Optional[dict] = None

        for i in range(self.MIN_BARS_FOR_REGIME, len(df)):
            window = df.iloc[: i + 1]
            bar = window.iloc[-1]

            if open_trade is not None:
                pnl = self._update_open_trade(open_trade, bar)
                if pnl is not None:
                    balance += pnl
                    trades.append(BacktestTrade(
                        instrument=instrument, direction=open_trade["direction"],
                        entry_time=open_trade["entry_time"], exit_time=bar.name,
                        entry_price=open_trade["entry_price"],
                        exit_price=open_trade["exit_price"],
                        pnl=pnl, strategy=open_trade["strategy"],
                        regime=open_trade["regime"],
                    ))
                    open_trade = None

            if open_trade is None:
                state = self._regime.classify(instrument, window)
                strategy = self._strategies.get(state.regime)
                if strategy:
                    signal = strategy.generate_signal(window, state)
                    if signal is not None:
                        decision = self._risk.evaluate(
                            signal=signal, balance=balance, open_positions=[],
                            daily_pnl=0, correlation_matrix={}, spread_ratio=0.5,
                        )
                        if decision.approved:
                            open_trade = {
                                "direction": signal.direction.value,
                                "entry_time": bar.name,
                                "entry_price": signal.entry_price,
                                "stop_loss": signal.stop_loss,
                                "take_profit": signal.take_profit,
                                "lot_size": decision.lot_size,
                                "strategy": signal.strategy,
                                "regime": state.regime.value,
                                "exit_price": None,
                            }
            equity.append(balance)

        equity_series = pd.Series(equity)
        pnls = pd.Series([t.pnl for t in trades]) if trades else pd.Series(dtype=float)
        returns = equity_series.pct_change().dropna()

        return BacktestResult(
            final_balance=balance, trades=trades, equity_curve=equity_series,
            metrics={
                "sharpe": sharpe_ratio(returns),
                "max_drawdown": max_drawdown(equity_series),
                "profit_factor": profit_factor(pnls) if len(pnls) else 0.0,
                "win_rate": win_rate(pnls) if len(pnls) else 0.0,
            },
        )

    @staticmethod
    def _update_open_trade(trade: dict, bar) -> Optional[float]:
        high, low = float(bar["high"]), float(bar["low"])
        sl, tp = trade["stop_loss"], trade["take_profit"]
        entry = trade["entry_price"]
        lot = trade["lot_size"]
        if trade["direction"] == "BUY":
            if low <= sl:
                trade["exit_price"] = sl
                return (sl - entry) * lot * 100000
            if high >= tp:
                trade["exit_price"] = tp
                return (tp - entry) * lot * 100000
        else:
            if high >= sl:
                trade["exit_price"] = sl
                return (entry - sl) * lot * 100000
            if low <= tp:
                trade["exit_price"] = tp
                return (entry - tp) * lot * 100000
        return None
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_backtest_runner.py -v`

- [ ] **Step 6: Commit**

```bash
git add bot/backtesting/runner.py bot/tests/fixtures/EURUSD.csv bot/tests/test_backtest_runner.py
git commit -m "feat(backtest): end-to-end runner threading regime → strategy → risk"
```

---

## Task 21: Bot orchestrator

**Files:**
- Create: `bot/src/bot.py`
- Create: `bot/tests/test_bot_orchestrator.py`

- [ ] **Step 1: Write failing test `bot/tests/test_bot_orchestrator.py`**

```python
import pytest
from unittest.mock import MagicMock
from src.bot import TradingBot
from src.config.schema import AppConfig
from src.mcp_client.fake import FakeMCPClient


def _config():
    return AppConfig(account={"starting_balance": 500}, instruments=["EURUSD"])


def _rates(n=500):
    return [{"time": 1704067200 + i * 3600, "open": 1.1, "high": 1.11,
             "low": 1.09, "close": 1.10 + 0.0001 * i, "tick_volume": 1000}
            for i in range(n)]


@pytest.mark.asyncio
async def test_runs_one_cycle():
    mcp = FakeMCPClient(responses={
        "get_rates": _rates(), "get_positions": [],
        "account_info": {"balance": 500},
        "get_symbol_info": {"spread": 1.0, "avg_spread": 1.0},
    })
    bot = TradingBot(config=_config(), mcp=mcp, supabase_logger=MagicMock())
    await bot.run_cycle()
    tool_names = [n for n, _ in mcp.calls]
    assert "get_rates" in tool_names
    assert "get_positions" in tool_names


@pytest.mark.asyncio
async def test_logs_regime_snapshot():
    mcp = FakeMCPClient(responses={
        "get_rates": _rates(), "get_positions": [],
        "account_info": {"balance": 500},
        "get_symbol_info": {"spread": 1.0, "avg_spread": 1.0},
    })
    supabase = MagicMock()
    await TradingBot(_config(), mcp, supabase).run_cycle()
    supabase.snapshot_regime.assert_called()
```

- [ ] **Step 2: Run (expect FAIL)**

Run: `cd bot && pytest tests/test_bot_orchestrator.py -v`

- [ ] **Step 3: Implement `bot/src/bot.py`**

```python
import logging
from src.config.schema import AppConfig
from src.data.cache import OHLCVCache
from src.data.fetcher import DataFetcher
from src.execution.engine import ExecutionEngine
from src.mcp_client.protocol import MCPClient
from src.models.regime import Regime
from src.portfolio.manager import PortfolioManager
from src.regime.detector import RegimeDetector
from src.risk.manager import RiskManager
from src.selection.instrument_selector import InstrumentSelector
from src.strategies.base import BaseStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy

log = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, config: AppConfig, mcp: MCPClient, supabase_logger):
        self._cfg = config
        self._mcp = mcp
        self._db = supabase_logger
        self._cache = OHLCVCache()
        self._fetcher = DataFetcher(mcp, self._cache)
        self._regime = RegimeDetector(config.regime)
        self._selector = InstrumentSelector(top_n=config.account.max_concurrent_positions)
        self._strategies: dict[Regime, BaseStrategy] = {
            Regime.TRENDING_UP: MomentumStrategy(config.strategy.momentum),
            Regime.TRENDING_DOWN: MomentumStrategy(config.strategy.momentum),
            Regime.RANGING: MeanReversionStrategy(config.strategy.mean_reversion),
        }
        self._risk = RiskManager(config.account)
        self._execution = ExecutionEngine(mcp)
        self._portfolio = PortfolioManager(mcp)

    async def run_cycle(self) -> None:
        await self._portfolio.sync()
        account = await self._mcp.call_tool("account_info", {})
        balance = float(account.get("balance", self._cfg.account.starting_balance))

        regime_states = []
        for instrument in self._cfg.instruments:
            df = await self._fetcher.fetch_ohlcv(
                instrument, self._cfg.timeframes.regime, bars=500,
            )
            state = self._regime.classify(instrument, df)
            regime_states.append(state)
            self._db.snapshot_regime(state)

        spread_ratios = await self._compute_spread_ratios()
        selected = self._selector.select(
            regime_states, spread_ratios,
            recent_sharpe={i: 1.0 for i in self._cfg.instruments},
        )

        for choice in selected:
            df = await self._fetcher.fetch_ohlcv(
                choice.instrument, self._cfg.timeframes.entry, bars=200,
            )
            state = next(s for s in regime_states if s.instrument == choice.instrument)
            strategy = self._strategies.get(state.regime)
            if strategy is None:
                continue
            signal = strategy.generate_signal(df, state)
            if signal is None:
                continue

            decision = self._risk.evaluate(
                signal=signal, balance=balance,
                open_positions=self._portfolio.positions,
                daily_pnl=self._portfolio.unrealized_pnl(),
                correlation_matrix={},
                spread_ratio=spread_ratios.get(choice.instrument, 1.0),
            )
            if not decision.approved:
                log.info(f"Signal rejected for {choice.instrument}: {decision.reason}")
                self._db.log_signal(signal, executed=False)
                continue

            result = await self._execution.place_order(signal, decision.lot_size)
            self._db.log_signal(signal, executed=(result.status == "FILLED"))
            log.info(f"Order placed for {choice.instrument}: ticket={result.ticket}")

    async def _compute_spread_ratios(self) -> dict[str, float]:
        ratios = {}
        for instrument in self._cfg.instruments:
            try:
                info = await self._mcp.call_tool("get_symbol_info", {"symbol": instrument})
                spread = float(info.get("spread", 1.0))
                avg = float(info.get("avg_spread", spread))
                ratios[instrument] = spread / avg if avg > 0 else 1.0
            except Exception:
                ratios[instrument] = 1.0
        return ratios
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `cd bot && pytest tests/test_bot_orchestrator.py -v`

- [ ] **Step 5: Commit**

```bash
git add bot/src/bot.py bot/tests/test_bot_orchestrator.py
git commit -m "feat(bot): TradingBot orchestrator threading full pipeline"
```

---

## Task 22: Entry point + full suite green

**Files:**
- Create: `bot/main.py`

- [ ] **Step 1: Implement `bot/main.py`**

```python
import asyncio
import logging
import os
import signal
from pathlib import Path
from supabase import create_client
from src.bot import TradingBot
from src.config.loader import load_config
from src.db.supabase_client import SupabaseLogger
from src.mcp_client.client import StdioMCPClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("algobot")


async def main():
    config = load_config(Path("config/settings.yaml"))
    supabase = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )
    db_logger = SupabaseLogger(supabase)

    mcp = StdioMCPClient()
    await mcp.connect()
    log.info("MCP connected")

    bot = TradingBot(config=config, mcp=mcp, supabase_logger=db_logger)
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)

    db_logger.update_bot_status("RUNNING")
    try:
        while not shutdown.is_set():
            try:
                await bot.run_cycle()
            except Exception as e:
                log.exception("Cycle failed")
                db_logger.update_bot_status("ERROR", error=str(e))
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                pass
    finally:
        db_logger.update_bot_status("STOPPED")
        await mcp.close()
        log.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the full test suite**

Run: `cd bot && pytest -v`
Expected: all tests pass.

- [ ] **Step 3: Run ruff lint**

Run: `cd bot && ruff check src backtesting tests`
Expected: no lint errors (fix any reported issues).

- [ ] **Step 4: Smoke test the backtest**

Run:
```bash
cd bot && python -c "
from pathlib import Path
from backtesting.runner import BacktestRunner
from backtesting.data_provider import CSVDataProvider
from src.config.schema import AppConfig
cfg = AppConfig(account={'starting_balance': 10000}, instruments=['EURUSD'])
r = BacktestRunner(cfg, CSVDataProvider(Path('tests/fixtures'))).run('EURUSD')
print('balance:', r.final_balance, 'trades:', len(r.trades), 'metrics:', r.metrics)
"
```
Expected: prints final balance, trade count, and metrics dict.

- [ ] **Step 5: Commit**

```bash
git add bot/main.py
git commit -m "feat(bot): main.py entry point with graceful shutdown"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-05-27-algobot-mt5-agentic-design.md`):

| Spec § | Item | Plan task |
|---|---|---|
| §6 | DataFetcher | T8 |
| §6 | RegimeDetector | T10 |
| §6 | InstrumentSelector | T11 |
| §6 | StrategyEngine (Momentum + MeanReversion + NoTrade-via-None) | T12, T13 |
| §6 | RiskManager | T14 |
| §6 | ExecutionEngine | T15 |
| §6 | PortfolioManager | T16 |
| §6 | Supabase persistence | T17 |
| §6 | Orchestrator | T21 |
| §9 | DB schema | T2 |
| §10 | YAML config | T3, T4 |
| §12 | Unit tests | every task |
| §12 | End-to-end backtest | T20 |
| §14 Phase 1 | "no AI, no dashboard" — explicit scope match |

**Phase 1 non-scope** (per spec §14): AI Agent (Phase 2), dashboard (Phase 4), paper trading (Phase 3), live deploy (Phase 5). Each gets its own future plan.

**Open items deferred to a Phase 1.5 follow-up plan** (not gaps — explicit decisions):
- Per-minute trailing-stop update loop in `run_cycle` — spec §8 line 3-6. Currently `run_cycle` covers H1/M15 logic only.
- Correlation matrix population — `run_cycle` passes `{}`; needs daily H1-close computation.
- Recent-Sharpe input to InstrumentSelector — currently mocked to 1.0 in orchestrator; compute from trade history once trades exist.
- Backtest CLI (Click-based `python -m backtesting.runner --instrument …`) — currently only smoke-tested directly.

**Type consistency:** `Signal`, `RegimeState`, `Position`, `MCPClient` protocol, and `RiskDecision` field names verified consistent across all tasks that reference them.

**Placeholder scan:** none found.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-27-algobot-phase1.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
