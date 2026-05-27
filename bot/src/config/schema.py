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
