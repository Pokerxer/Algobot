from enum import Enum
from typing import Optional
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
    atr: Optional[float] = None
