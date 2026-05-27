import pandas as pd
import pandas_ta as ta


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    result = ta.adx(df["high"], df["low"], df["close"], length=period)
    if result is None:
        raise ValueError("ADX calculation failed")
    return result.rename(columns={
        f"ADX_{period}": "adx",
        f"DMP_{period}": "plus_di",
        f"DMN_{period}": "minus_di",
    })


def compute_bb_width(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.Series:
    bb = ta.bbands(df["close"], length=period, std=std)
    if bb is None:
        raise ValueError("Bollinger Bands calculation failed")
    upper = bb[f"BBU_{period}_{std}_{std}"]
    lower = bb[f"BBL_{period}_{std}_{std}"]
    middle = bb[f"BBM_{period}_{std}_{std}"]
    return (upper - lower) / middle


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.atr(df["high"], df["low"], df["close"], length=period)
