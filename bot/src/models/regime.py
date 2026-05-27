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
