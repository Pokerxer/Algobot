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
