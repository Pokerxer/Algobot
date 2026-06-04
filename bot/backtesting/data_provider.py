from pathlib import Path
from typing import Optional
import pandas as pd


class CSVDataProvider:
    def __init__(self, directory: Path):
        self._dir = directory

    def load(self, instrument: str, timeframe: str = "H1",
             start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        # Support both {instrument}_{timeframe}.csv and legacy {instrument}.csv
        path = self._dir / f"{instrument}_{timeframe}.csv"
        if not path.exists():
            path = self._dir / f"{instrument}.csv"
        df = pd.read_csv(path)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        return df[["open", "high", "low", "close", "volume"]]
