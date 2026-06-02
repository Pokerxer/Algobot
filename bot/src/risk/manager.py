from dataclasses import dataclass
from typing import Optional
from src.config.schema import AccountConfig
from src.models.position import Position
from src.models.signal import Signal


@dataclass
class RiskDecision:
    approved: bool
    lot_size: float = 0.0
    reason: str = ""


# (pip_size_in_price, usd_per_pip_per_standard_lot)
# pip_size: price change that equals 1 pip for this instrument category
# pip_value: USD profit/loss per pip for 1 standard lot
_INSTRUMENT_SPECS: dict[str, tuple[float, float]] = {
    "JPY": (0.01,   9.0),    # 3-decimal JPY pairs
    "XAU": (0.01,   1.0),    # Gold  (100 oz/lot, $0.01 tick → $1/lot/pip)
    "XAG": (0.001,  0.5),    # Silver
    # Exness index specs (verified from MT5 symbol_info):
    # point=0.01, tick_size=0.01, tick_value=$0.01/lot
    "US5": (0.01,   0.01),   # US500m  — S&P 500
    "UST": (0.01,   0.01),   # USTECm  — NASDAQ-100
    "NAS": (0.01,   0.01),   # NAS100  — NASDAQ (alternative)
    # US30m: point=0.1, tick_size=0.1, tick_value=$0.10/lot
    "US3": (0.1,    0.10),   # US30m   — Dow Jones
    "GER": (0.1,    1.0),    # DAX
    "UK1": (0.1,    1.0),    # FTSE
    # Crypto: 1 lot = 1 coin; BTC $1 tick = $1/lot, ETH $0.10 tick = $0.10/lot
    "BTC": (1.0,    1.0),    # BTCUSDm
    "ETH": (0.1,    0.1),    # ETHUSDm
}
_FOREX_DEFAULT = (0.0001, 10.0)   # 4-decimal forex pairs

# Hardcoded correlation pairs that are always enforced regardless of live matrix.
# BTC and ETH move together (ρ ≈ 0.90 intraday) — same-direction dual crypto blocked.
_HARDCODED_CORRELATIONS: dict[tuple[str, str], float] = {
    ("BTCUSDm", "ETHUSDm"): 0.90,
    ("ETHUSDm", "BTCUSDm"): 0.90,
    ("US30m",   "US500m"):  0.92,
    ("US500m",  "US30m"):   0.92,
    ("XAGUSDm", "XAUUSDm"): 0.85,
    ("XAUUSDm", "XAGUSDm"): 0.85,
}


def _pip_spec(instrument: str) -> tuple[float, float]:
    clean = instrument.rstrip("m").upper()
    for prefix, spec in _INSTRUMENT_SPECS.items():
        if clean.startswith(prefix):
            return spec
    if "JPY" in clean:          # catches USDJPY, EURJPY, GBPJPY …
        return (0.01, 9.0)
    return _FOREX_DEFAULT


class RiskManager:
    CORRELATION_THRESHOLD = 0.7
    MAX_SPREAD_MULTIPLIER = 2.0

    def __init__(self, config: AccountConfig, pip_value: float = 10.0):
        self._cfg = config
        self._default_pip_value = pip_value  # kept for API compatibility

    def evaluate(self, signal: Signal, balance: float,
                 open_positions: list[Position], daily_pnl: float,
                 correlation_matrix: dict[tuple[str, str], float],
                 spread_ratio: float) -> RiskDecision:
        if len(open_positions) >= self._cfg.max_concurrent_positions:
            return RiskDecision(False, reason="Max concurrent positions reached")

        max_dd = balance * (self._cfg.max_daily_drawdown_pct / 100)
        if daily_pnl <= -max_dd:
            return RiskDecision(False, reason=f"Daily drawdown breached ({daily_pnl})")

        if spread_ratio > self.MAX_SPREAD_MULTIPLIER:
            return RiskDecision(False, reason=f"Spread too wide ({spread_ratio:.2f}x)")

        for pos in open_positions:
            if pos.instrument == signal.instrument:
                return RiskDecision(False, reason="Already have position in this instrument")
            corr = self._lookup_correlation(correlation_matrix, signal.instrument, pos.instrument)
            if corr is not None and corr > self.CORRELATION_THRESHOLD and pos.direction == signal.direction:
                return RiskDecision(False, reason=f"Correlated position open (corr={corr:.2f})")

        # Confidence-weighted sizing: scale 0.5× at zero confidence, 1.5× at full.
        # This rewards high-conviction setups while reducing exposure on marginal ones.
        confidence_scale = 0.5 + signal.confidence   # 0.5 → 1.5 across the confidence range
        risk_amount = balance * (self._cfg.risk_per_trade_pct / 100) * confidence_scale
        stop_distance = abs(signal.entry_price - signal.stop_loss)
        if stop_distance <= 0:
            return RiskDecision(False, reason="Invalid stop distance")

        pip_size, pip_value = _pip_spec(signal.instrument)

        # Per-instrument minimum stop in pips.
        # Set to ~50% of typical M15 ATR so normal volatility always clears the bar.
        # Old values were calibrated for lower_band - 1×ATR; new formula is
        # close - 1×ATR so stop_distance == 1×ATR exactly — mins must be ≤ ATR.
        _min_pips: dict[str, float] = {
            "XAU":  800,   # gold:   $8 min  (800 pips × $0.01) — M15 ATR ~$10-25
            "XAG":   80,   # silver: $0.08 min (80 pips × $0.001) — M15 ATR ~$0.15-0.35
            "US5":  500,   # US500:  $5 min  (500 × $0.01) — M15 ATR ~$8-20
            "UST": 1500,   # USTEC:  $15 min (1500 × $0.01) — M15 ATR ~$20-50
            "NAS": 1500,   # NAS100: same as USTEC
            "US3":  200,   # US30:   $20 min (200 × $0.10) — M15 ATR ~$30-80
            "JPY":    8,   # JPY pairs: 8 pips — M15 ATR ~20-35 pips
            "BTC":  150,   # BTC:  $150 min (150 × $1.0) — M15 ATR ~$200-400
            "ETH":   60,   # ETH:  $6 min  (60 × $0.10)  — M15 ATR ~$10-20
        }
        clean = signal.instrument.rstrip("m").upper()
        min_stop_pips = next(
            (v for k, v in _min_pips.items() if clean.startswith(k)),
            5.0,   # default: 5 pips for 4-decimal forex (M15 ATR ~8-12 pips)
        )
        actual_pips = stop_distance / pip_size
        if actual_pips < min_stop_pips:
            return RiskDecision(False, reason=f"Stop too tight ({actual_pips:.0f} pips < {min_stop_pips:.0f} min for {signal.instrument})")

        pip_distance = stop_distance / pip_size
        lot_size = round(risk_amount / (pip_distance * pip_value), 2)
        if lot_size < 0.01:
            return RiskDecision(False, reason=f"Lot size below broker minimum ({lot_size:.4f})")

        # Hard cap: no single position larger than 5% of balance in notional risk
        max_risk_pct = 5.0
        if (lot_size * pip_distance * pip_value) > balance * (max_risk_pct / 100):
            lot_size = round(balance * (max_risk_pct / 100) / (pip_distance * pip_value), 2)
            lot_size = max(lot_size, 0.01)

        return RiskDecision(approved=True, lot_size=lot_size, reason="OK")

    @staticmethod
    def _lookup_correlation(matrix, a, b) -> Optional[float]:
        hardcoded = _HARDCODED_CORRELATIONS.get((a, b)) or _HARDCODED_CORRELATIONS.get((b, a))
        if hardcoded is not None:
            return hardcoded
        return matrix.get((a, b)) or matrix.get((b, a))
