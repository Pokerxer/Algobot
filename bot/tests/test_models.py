import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from src.models.signal import Signal, Direction
from src.models.regime import RegimeState, Regime
from src.models.position import Position


def test_signal_construction():
    sig = Signal(
        instrument="EURUSD", direction=Direction.BUY,
        entry_price=1.085, stop_loss=1.082, take_profit=1.091,
        confidence=0.75, regime=Regime.TRENDING_UP, strategy="momentum",
    )
    assert sig.confidence == 0.75


def test_signal_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        Signal(
            instrument="EURUSD", direction=Direction.BUY,
            entry_price=1, stop_loss=0.9, take_profit=1.1,
            confidence=1.5, regime=Regime.TRENDING_UP, strategy="momentum",
        )


def test_regime_state_construction():
    rs = RegimeState(
        instrument="XAUUSD", regime=Regime.RANGING, confidence=0.8,
        indicators={"adx": 15.2, "bb_width": 0.012},
    )
    assert rs.regime == Regime.RANGING


def test_position_construction():
    pos = Position(
        ticket=12345, instrument="EURUSD", direction=Direction.BUY,
        entry_price=1.085, volume=0.01, stop_loss=1.082, take_profit=1.091,
        opened_at=datetime.now(timezone.utc), strategy="momentum",
        regime=Regime.TRENDING_UP,
    )
    assert pos.profit == 0
