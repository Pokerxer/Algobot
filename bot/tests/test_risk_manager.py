from datetime import datetime, timezone
from src.risk.manager import RiskManager
from src.config.schema import AccountConfig
from src.models.signal import Signal, Direction
from src.models.regime import Regime
from src.models.position import Position


def _sig(inst="EURUSD", entry=1.085, stop=1.082, tp=1.091, direction=Direction.BUY):
    return Signal(instrument=inst, direction=direction, entry_price=entry,
                  stop_loss=stop, take_profit=tp, confidence=0.7,
                  regime=Regime.TRENDING_UP, strategy="momentum")


def _pos(inst="EURUSD", direction=Direction.BUY):
    return Position(ticket=1, instrument=inst, direction=direction,
                    entry_price=1.085, volume=0.01,
                    opened_at=datetime.now(timezone.utc),
                    strategy="momentum", regime=Regime.TRENDING_UP)


def test_sizing_one_percent_risk():
    rm = RiskManager(AccountConfig(starting_balance=10000), pip_value=10)
    d = rm.evaluate(signal=_sig(entry=1.085, stop=1.082), balance=10000,
                    open_positions=[], daily_pnl=0,
                    correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is True
    assert abs(d.lot_size - 0.33) < 0.01


def test_rejects_at_max_positions():
    rm = RiskManager(AccountConfig(starting_balance=500, max_concurrent_positions=3))
    d = rm.evaluate(signal=_sig("EURUSD"), balance=500,
                    open_positions=[_pos("GBPUSD"), _pos("USDJPY"), _pos("XAUUSD")],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is False
    assert "concurrent" in d.reason.lower()


def test_rejects_when_drawdown_breached():
    rm = RiskManager(AccountConfig(starting_balance=500, max_daily_drawdown_pct=5))
    d = rm.evaluate(signal=_sig(), balance=475, open_positions=[],
                    daily_pnl=-30, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is False
    assert "drawdown" in d.reason.lower()


def test_rejects_wide_spread():
    rm = RiskManager(AccountConfig(starting_balance=500))
    d = rm.evaluate(signal=_sig(), balance=500, open_positions=[],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=2.5)
    assert d.approved is False
    assert "spread" in d.reason.lower()


def test_rejects_correlated_same_direction():
    rm = RiskManager(AccountConfig(starting_balance=500))
    d = rm.evaluate(signal=_sig("EURUSD", direction=Direction.BUY), balance=500,
                    open_positions=[_pos("GBPUSD", direction=Direction.BUY)],
                    daily_pnl=0,
                    correlation_matrix={("EURUSD", "GBPUSD"): 0.85},
                    spread_ratio=0.1)
    assert d.approved is False


def test_approves_correlated_opposite_direction():
    rm = RiskManager(AccountConfig(starting_balance=500))
    d = rm.evaluate(signal=_sig("EURUSD", direction=Direction.BUY), balance=500,
                    open_positions=[_pos("GBPUSD", direction=Direction.SELL)],
                    daily_pnl=0,
                    correlation_matrix={("EURUSD", "GBPUSD"): 0.85},
                    spread_ratio=0.1)
    assert d.approved is True
