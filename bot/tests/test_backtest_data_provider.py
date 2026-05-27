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
