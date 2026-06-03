"""Change of Character (CHoCH) indicator — SMC market structure detection.

CHoCH is the *first* opposing Break of Structure — the earliest signal that
the prevailing market structure has shifted direction. It differs from a plain
BOS (Break of Structure, which is a trend-continuation signal) in that it
represents a character change: an up-trending market printing a lower low
through a key swing, or a down-trending market printing a higher high.

Usage in RegimeDetector:
  After ADX-based classification, if the ADX says RANGING or CHOPPY but a
  recent bearish CHoCH has fired on H1, the true structure may already be
  bearish — override the regime to TRENDING_DOWN (and vice versa for bullish).
  This prevents mean-reversion BUY entries into an already-bearish structure.

Return values of detect_recent_choch:
  'bearish'  — price recently broke a prior swing low (structure turned down)
  'bullish'  — price recently broke a prior swing high (structure turned up)
  None       — no recent CHoCH, computation error, or insufficient data

Fail-open: errors return None so the caller keeps its existing regime.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

import pandas as pd

log = logging.getLogger(__name__)

_MIN_BARS = 80   # need enough history to form meaningful swings


def detect_recent_choch(
    df: pd.DataFrame,
    swing_length: int = 10,
    lookback: int = 15,
) -> Optional[Literal["bullish", "bearish"]]:
    """Return the direction of the most recent CHoCH within `lookback` bars.

    Args:
        df:           OHLCV DataFrame (lowercase columns including 'volume').
        swing_length: Pivot strength — how many bars each side define a swing.
        lookback:     A CHoCH is 'recent' if its BrokenIndex >= len(df)-lookback.

    Returns:
        'bearish'  if a bearish CHoCH was confirmed within the last `lookback` bars.
        'bullish'  if a bullish CHoCH was confirmed within the last `lookback` bars.
        None       if no recent CHoCH or computation failed (fail-open).
    """
    if len(df) < _MIN_BARS:
        return None
    try:
        from smartmoneyconcepts import smc
        swing = smc.swing_highs_lows(df, swing_length=swing_length)
        bc = smc.bos_choch(df, swing)
        choch = bc[bc["CHOCH"].notna() & (bc["CHOCH"] != 0)].copy()
        if choch.empty:
            return None

        threshold = len(df) - lookback
        recent = choch[choch["BrokenIndex"].notna() & (choch["BrokenIndex"] >= threshold)]
        if recent.empty:
            return None

        # Use the most recently confirmed CHoCH (highest BrokenIndex)
        latest = recent.loc[recent["BrokenIndex"].idxmax()]
        return "bearish" if float(latest["CHOCH"]) < 0 else "bullish"

    except Exception as exc:
        log.debug("CHoCH computation failed (%s) — failing open", exc)
        return None
