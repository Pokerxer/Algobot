"""Order Block indicator — SMC institutional price zone detection.

Wraps the `smartmoneyconcepts` library to detect bullish and bearish
order blocks (OBs) from OHLCV data and check whether a given price is
within an active OB zone.

A *bullish OB* is the last bearish candle before a significant upward
impulse — the zone where institutions accumulated buy orders.
A *bearish OB* is the last bullish candle before a significant downward
impulse — the zone where institutions accumulated sell orders.

OBs that have been mitigated (price closed through them) are excluded —
a mitigated OB becomes a "breaker block" and flips polarity in SMC.

Usage in mean-reversion:
  - Only take a BUY signal if the current price is at a fresh bullish OB.
  - Only take a SELL signal if the current price is at a fresh bearish OB.

Fail-open semantics: any error (import failure, insufficient data,
computation exception) returns True so that OB unavailability never
silently blocks trading.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

_MIN_BARS = 50   # need enough history to form meaningful swings

# Per-instrument swing sensitivity.
# High-volatility instruments need wider swings to capture institutional zones cleanly.
# XAU/indices/crypto: swing_length=20; forex: 10.
_SWING_LENGTHS: dict[str, int] = {
    "XAU": 20, "XAG": 20,
    "US5": 20, "US3": 20, "UST": 20,
    "BTC": 20, "ETH": 20,
}

# ICT kill zones (UTC hours, inclusive start / exclusive end).
# OBs formed inside kill zones represent genuine institutional displacement.
# Outside kill zones → use stricter tolerance so only clean OB touches qualify.
_KILL_ZONES: list[tuple[int, int]] = [(7, 10), (12, 15)]   # London open, NY open


def _swing_length_for(instrument: str) -> int:
    clean = instrument.rstrip("m").upper()
    for prefix, sl in _SWING_LENGTHS.items():
        if clean.startswith(prefix):
            return sl
    return 10


def in_kill_zone() -> bool:
    """Return True if the current UTC hour falls within a London or NY kill zone."""
    hour = datetime.now(timezone.utc).hour
    return any(start <= hour < end for start, end in _KILL_ZONES)


def _compute_obs(df: pd.DataFrame, swing_length: int = 10) -> Optional[pd.DataFrame]:
    """Return fresh (unmitigated) OB DataFrame, or None on computation failure.

    Distinguishes between:
      None         → computation failed → fail open (True)
      empty df     → computation worked, no fresh OBs → block (False)
      non-empty df → fresh OBs exist → check price
    """
    if len(df) < _MIN_BARS:
        return None
    try:
        from smartmoneyconcepts import smc
        swing = smc.swing_highs_lows(df, swing_length=swing_length)
        ob = smc.ob(df, swing)
        # MitigatedIndex == 0 means the OB is still fresh (0 is the sentinel value).
        # MitigatedIndex > 0 means it was traded through at that bar — exclude it.
        return ob[
            ob["OB"].notna() & (ob["OB"] != 0) & (ob["MitigatedIndex"] == 0)
        ].copy()
    except Exception as exc:
        log.debug("OB computation failed (%s) — failing open", exc)
        return None


def price_at_bullish_ob(df: pd.DataFrame, price: float,
                         instrument: str = "",
                         lookback: int = 30,
                         tolerance: float = 0.003) -> bool:
    """Return True if `price` is within a recent, fresh bullish order block zone.

    Args:
        df:         OHLCV DataFrame (lowercase columns including 'volume').
        price:      The current close price to check.
        instrument: Symbol name (e.g. 'XAUUSDm') — used to select swing sensitivity.
        lookback:   How many of the most-recent OBs to scan.
        tolerance:  Fractional allowance below OB bottom (e.g. 0.003 = 0.3%).

    Returns True (fail-open) if OBs cannot be computed.
    """
    sl = _swing_length_for(instrument)
    obs = _compute_obs(df, swing_length=sl)
    if obs is None:
        return True   # fail open

    bullish = obs[obs["OB"] == 1.0].tail(lookback)
    if bullish.empty:
        return False  # fresh OBs computed but none are bullish

    for _, row in bullish.iterrows():
        bottom = float(row["Bottom"])
        top    = float(row["Top"])
        if bottom * (1 - tolerance) <= price <= top:
            return True
    return False


def price_at_bearish_ob(df: pd.DataFrame, price: float,
                         instrument: str = "",
                         lookback: int = 30,
                         tolerance: float = 0.003) -> bool:
    """Return True if `price` is within a recent, fresh bearish order block zone.

    Returns True (fail-open) if OBs cannot be computed.
    """
    sl = _swing_length_for(instrument)
    obs = _compute_obs(df, swing_length=sl)
    if obs is None:
        return True   # fail open

    bearish = obs[obs["OB"] == -1.0].tail(lookback)
    if bearish.empty:
        return False  # fresh OBs computed but none are bearish

    for _, row in bearish.iterrows():
        bottom = float(row["Bottom"])
        top    = float(row["Top"])
        if bottom <= price <= top * (1 + tolerance):
            return True
    return False
