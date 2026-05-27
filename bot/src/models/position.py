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
