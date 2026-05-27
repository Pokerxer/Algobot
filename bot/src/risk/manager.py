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


class RiskManager:
    CORRELATION_THRESHOLD = 0.7
    MAX_SPREAD_MULTIPLIER = 2.0

    def __init__(self, config: AccountConfig, pip_value: float = 10.0):
        self._cfg = config
        self._pip_value = pip_value

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

        risk_amount = balance * (self._cfg.risk_per_trade_pct / 100)
        stop_distance = abs(signal.entry_price - signal.stop_loss)
        if stop_distance <= 0:
            return RiskDecision(False, reason="Invalid stop distance")
        pip_distance = stop_distance * 10000
        lot_size = round(risk_amount / (pip_distance * self._pip_value), 2)
        if lot_size < 0.01:
            return RiskDecision(False, reason="Lot size below broker minimum")

        return RiskDecision(approved=True, lot_size=lot_size, reason="OK")

    @staticmethod
    def _lookup_correlation(matrix, a, b) -> Optional[float]:
        return matrix.get((a, b)) or matrix.get((b, a))
