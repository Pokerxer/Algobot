from src.selection.instrument_selector import InstrumentSelector, InstrumentScore
from src.models.regime import Regime, RegimeState


def _state(inst, regime, conf):
    return RegimeState(instrument=inst, regime=regime, confidence=conf,
                       indicators={"adx": 30})


def test_ranks_by_confidence_when_other_factors_equal():
    states = [
        _state("EURUSD", Regime.TRENDING_UP, 0.9),
        _state("GBPUSD", Regime.TRENDING_UP, 0.5),
    ]
    spread = {"EURUSD": 0.1, "GBPUSD": 0.1}
    sharpe = {"EURUSD": 1.0, "GBPUSD": 1.0}
    selected = InstrumentSelector(top_n=1).select(states, spread, sharpe)
    assert selected[0].instrument == "EURUSD"


def test_excludes_choppy_instruments():
    states = [
        _state("EURUSD", Regime.CHOPPY, 0.9),
        _state("GBPUSD", Regime.TRENDING_UP, 0.6),
    ]
    selected = InstrumentSelector(top_n=2).select(
        states, {"EURUSD": 0.1, "GBPUSD": 0.1}, {"EURUSD": 1, "GBPUSD": 1},
    )
    assert all(s.instrument != "EURUSD" for s in selected)


def test_penalizes_high_spread_cost():
    states = [
        _state("EURUSD", Regime.TRENDING_UP, 0.8),
        _state("XAUUSD", Regime.TRENDING_UP, 0.8),
    ]
    selected = InstrumentSelector(top_n=1).select(
        states, {"EURUSD": 0.05, "XAUUSD": 0.5}, {"EURUSD": 1.0, "XAUUSD": 1.0},
    )
    assert selected[0].instrument == "EURUSD"
