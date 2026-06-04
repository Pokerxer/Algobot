"""Order Block indicator — SMC institutional price zone detection.

Wraps the `smartmoneyconcepts` library to detect bullish and bearish
order blocks (OBs) from OHLCV data and check whether a given price is
within an active OB zone.

A *bullish OB* is the last bearish candle before a significant upward
impulse — the zone where institutions accumulated buy orders.
A *bearish OB* is the last bullish candle before a significant downward
impulse — the zone where institutions accumulated sell orders.

Usage in mean-reversion:
  - Only take a BUY signal if the current price is at a bullish OB.
  - Only take a SELL signal if the current price is at a bearish OB.

Fail-open semantics: any error (import failure, insufficient data,
computation exception) returns True so that OB unavailability never
silently blocks trading.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

# Minimum bars required to compute meaningful swing highs/lows and OBs.
_MIN_BARS = 50
_SWING_LENGTH = 10   # bars each side to identify a swing pivot


def _compute_obs(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Return active OB DataFrame, or None only on computation failure.

    Distinguishes between:
      None         → computation failed (library error, insufficient data) → fail open
      empty df     → computation worked but no OBs found → block signal (no support)
      non-empty df → OBs found → check price
    """
    if len(df) < _MIN_BARS:
        return None
    try:
        from smartmoneyconcepts import smc
        swing = smc.swing_highs_lows(df, swing_length=_SWING_LENGTH)
        ob = smc.ob(df, swing)
        return ob[ob["OB"].notna() & (ob["OB"] != 0)].copy()
    except Exception as exc:
        log.debug("OB computation failed (%s) — failing open", exc)
        return None


def price_at_bullish_ob(df: pd.DataFrame, price: float,
                         lookback: int = 30,
                         tolerance: float = 0.003) -> bool:
    """Return True if `price` is within a recent bullish order block zone.

    Args:
        df:        OHLCV DataFrame (lowercase columns including 'volume').
        price:     The current close price to check.
        lookback:  How many of the most-recent OBs to scan.
        tolerance: Fractional allowance below OB bottom (e.g. 0.003 = 0.3%).

    Returns True (fail-open) if OBs cannot be computed.
    """
    obs = _compute_obs(df)
    if obs is None:
        return True   # fail open — no data / library not available

    bullish = obs[obs["OB"] == 1.0].tail(lookback)
    if bullish.empty:
        return False  # OBs computed successfully but none are bullish → no support

    for _, row in bullish.iterrows():
        bottom = float(row["Bottom"])
        top    = float(row["Top"])
        # Price is "at" the OB if it's within or just below the zone
        if bottom * (1 - tolerance) <= price <= top:
            return True
    return False


def price_at_bearish_ob(df: pd.DataFrame, price: float,
                         lookback: int = 30,
                         tolerance: float = 0.003) -> bool:
    """Return True if `price` is within a recent bearish order block zone.

    Returns True (fail-open) if OBs cannot be computed.
    """
    obs = _compute_obs(df)
    if obs is None:
        return True   # fail open

    bearish = obs[obs["OB"] == -1.0].tail(lookback)
    if bearish.empty:
        return False  # OBs computed but none are bearish → no resistance

    for _, row in bearish.iterrows():
        bottom = float(row["Bottom"])
        top    = float(row["Top"])
        # Price is "at" the OB if it's within or just above the zone
        if bottom <= price <= top * (1 + tolerance):
            return True
    return False
