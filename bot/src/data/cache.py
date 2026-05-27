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
