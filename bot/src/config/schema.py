from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class AccountConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starting_balance: float = Field(gt=0)
    max_daily_drawdown_pct: float = 5
    max_concurrent_positions: int = 5
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
    choch_supplement: bool = True   # override RANGING/CHOPPY if a recent CHoCH has fired
    choch_lookback: int = 15        # bars — CHoCH BrokenIndex must be within this window
    choch_swing_length: int = 10    # pivot sensitivity for CHoCH swing detection


class MomentumStrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fast_ema: int = 20
    slow_ema: int = 50
    atr_stop_multiplier: float = 1.5
    atr_target_multiplier: float = 3.0
    rsi_period: int = 14          # RSI confirmation period
    rsi_midline: float = 50.0     # BUY only when RSI > midline; SELL when RSI < midline


class MeanReversionStrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rsi_period: int = 14
    rsi_oversold: float = 30           # RSI threshold for oversold (tighten to 25 in prod)
    rsi_overbought: float = 70         # RSI threshold for overbought (tighten to 75 in prod)
    bb_std: float = 2.0                # Bollinger Band std multiplier (1.5 for tight-ranging pairs like EURUSD)
    require_double_touch: bool = False  # second band touch confirms entry (enable in prod)
    require_divergence: bool = False    # RSI must be less oversold at second touch (divergence)
    bb_expansion_filter: bool = False   # reject expanding bands (enable in prod via settings)
    require_order_block: bool = True    # only enter at institutional OB zones (SMC filter)
    require_liquidity_sweep: bool = True  # enter only after band is swept and price recovers


class LondonBreakoutStrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_start_utc: int = 7
    session_end_utc: int = 10
    tp_multiplier: float = 1.5
    min_range_pips: float = 10.0
    pairs: list[str] = Field(default_factory=lambda: [
        "EURUSDm", "GBPUSDm", "USDJPYm"
    ])


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    momentum: MomentumStrategyConfig = MomentumStrategyConfig()
    mean_reversion: MeanReversionStrategyConfig = MeanReversionStrategyConfig()
    london_breakout: LondonBreakoutStrategyConfig = LondonBreakoutStrategyConfig()


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
