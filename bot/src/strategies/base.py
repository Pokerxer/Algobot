from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd
from src.models.regime import RegimeState
from src.models.signal import Signal


class BaseStrategy(ABC):
    name: str

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, regime: RegimeState) -> Optional[Signal]: ...
