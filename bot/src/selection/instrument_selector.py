from dataclasses import dataclass
from src.models.regime import Regime, RegimeState


@dataclass
class InstrumentScore:
    instrument: str
    score: float
    regime: Regime
    confidence: float


class InstrumentSelector:
    def __init__(self, top_n: int = 3):
        self._top_n = top_n

    def select(
        self, regime_states: list[RegimeState],
        spread_ratios: dict[str, float], recent_sharpe: dict[str, float],
    ) -> list[InstrumentScore]:
        scores = []
        for rs in regime_states:
            if rs.regime == Regime.CHOPPY:
                continue
            spread = spread_ratios.get(rs.instrument, 1.0)
            sharpe = max(recent_sharpe.get(rs.instrument, 0.0), 0.0)
            score = rs.confidence * sharpe * (1.0 / max(spread, 0.001))
            scores.append(InstrumentScore(
                instrument=rs.instrument, score=score,
                regime=rs.regime, confidence=rs.confidence,
            ))
        scores.sort(key=lambda s: s.score, reverse=True)
        return scores[: self._top_n]
