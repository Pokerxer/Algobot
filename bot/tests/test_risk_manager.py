from datetime import datetime, timezone
from src.risk.manager import RiskManager
from src.config.schema import AccountConfig
from src.models.signal import Signal, Direction
from src.models.regime import Regime
from src.models.position import Position


def _sig(inst="EURUSD", entry=1.085, stop=1.082, tp=1.091,
         direction=Direction.BUY, confidence=0.5):
    return Signal(instrument=inst, direction=direction, entry_price=entry,
                  stop_loss=stop, take_profit=tp, confidence=confidence,
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


def test_confidence_half_scales_lot_size_down():
    """confidence=0.0 → scale 0.5 → half the base lot."""
    rm = RiskManager(AccountConfig(starting_balance=10000), pip_value=10)
    sig = Signal(instrument="EURUSD", direction=Direction.BUY,
                 entry_price=1.085, stop_loss=1.082, take_profit=1.091,
                 confidence=0.0, regime=Regime.TRENDING_UP, strategy="momentum")
    d = rm.evaluate(signal=sig, balance=10000, open_positions=[],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is True
    # 0.5% of 10000 = 50 / (30 pips × $10) = 0.17 lots
    assert abs(d.lot_size - 0.17) < 0.01


def test_confidence_full_scales_lot_size_up():
    """confidence=1.0 → scale 1.5 → one-and-a-half the base lot."""
    rm = RiskManager(AccountConfig(starting_balance=10000), pip_value=10)
    sig = Signal(instrument="EURUSD", direction=Direction.BUY,
                 entry_price=1.085, stop_loss=1.082, take_profit=1.091,
                 confidence=1.0, regime=Regime.TRENDING_UP, strategy="momentum")
    d = rm.evaluate(signal=sig, balance=10000, open_positions=[],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is True
    # 1.5% of 10000 = 150 / (30 pips × $10) = 0.50 lots
    assert abs(d.lot_size - 0.50) < 0.01


def test_approves_correlated_opposite_direction():
    rm = RiskManager(AccountConfig(starting_balance=500))
    d = rm.evaluate(signal=_sig("EURUSD", direction=Direction.BUY), balance=500,
                    open_positions=[_pos("GBPUSD", direction=Direction.SELL)],
                    daily_pnl=0,
                    correlation_matrix={("EURUSD", "GBPUSD"): 0.85},
                    spread_ratio=0.1)
    assert d.approved is True


# ── BTC / ETH pip specs ───────────────────────────────────────────────────────

def test_btc_lot_size_is_micro():
    """BTC/USD with $500 stop: sizing produces a tiny lot on a $1500 account."""
    rm = RiskManager(AccountConfig(starting_balance=1500))
    sig = _sig(inst="BTCUSDm", entry=67000.0, stop=66500.0, tp=68500.0)
    d = rm.evaluate(signal=sig, balance=1500, open_positions=[],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is True
    # risk = 1500 × 1% × 1.0 (confidence scale) = $15
    # pip_size=1.0, pip_distance=500, pip_value=$1 → lot = 15/(500×1) = 0.03
    assert abs(d.lot_size - 0.03) < 0.01


def test_eth_lot_size_is_micro():
    """ETH/USD with $150 stop: correct lot size on $1500 account."""
    rm = RiskManager(AccountConfig(starting_balance=1500))
    sig = _sig(inst="ETHUSDm", entry=3500.0, stop=3350.0, tp=3950.0)
    d = rm.evaluate(signal=sig, balance=1500, open_positions=[],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is True
    # risk = $15, pip_size=0.1, pip_distance=1500, pip_value=$0.1
    # lot = 15/(1500×0.1) = 0.10
    assert abs(d.lot_size - 0.10) < 0.01


# ── BTC–ETH hardcoded correlation ────────────────────────────────────────────

def test_btc_eth_hardcoded_correlation_blocks_same_direction():
    """BTC and ETH have a hardcoded 0.90 correlation — same-direction positions blocked."""
    rm = RiskManager(AccountConfig(starting_balance=1500))
    sig = _sig(inst="ETHUSDm", entry=3500.0, stop=3350.0, tp=3950.0,
               direction=Direction.BUY)
    btc_pos = _pos("BTCUSDm", direction=Direction.BUY)
    d = rm.evaluate(signal=sig, balance=1500, open_positions=[btc_pos],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is False
    assert "corr" in d.reason.lower()


def test_btc_eth_hardcoded_correlation_allows_opposite_direction():
    """Opposite-direction BTC/ETH positions are not blocked by the correlation guard."""
    rm = RiskManager(AccountConfig(starting_balance=1500))
    sig = _sig(inst="ETHUSDm", entry=3500.0, stop=3350.0, tp=3950.0,
               direction=Direction.SELL)
    btc_pos = _pos("BTCUSDm", direction=Direction.BUY)
    d = rm.evaluate(signal=sig, balance=1500, open_positions=[btc_pos],
                    daily_pnl=0, correlation_matrix={}, spread_ratio=0.1)
    assert d.approved is True
