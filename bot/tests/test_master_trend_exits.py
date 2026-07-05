from datetime import datetime, timezone

from src.models.position import Position
from src.models.regime import Regime
from src.models.signal import Direction


def _pos(entry, sl, direction=Direction.BUY, ticket=1):
    return Position(
        ticket=ticket, instrument="US30m", direction=direction,
        entry_price=entry, current_price=entry, volume=1.0, profit=0.0,
        stop_loss=sl, take_profit=None,
        opened_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        strategy="master_trend", regime=Regime.TRENDING_UP,
    )


def _bot():
    # Build a TradingBot without __init__; only config + caches are used here.
    from src.bot import TradingBot
    from src.config.schema import AppConfig, AccountConfig
    cfg = AppConfig(account=AccountConfig(starting_balance=1500), instruments=["US30m"])
    bot = TradingBot.__new__(TradingBot)
    bot._cfg = cfg
    bot._mt_r_dist = {}
    bot._mt_high_water = {}
    return bot


def test_breakeven_moves_sl_to_entry_at_2r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40
    pos = _pos(entry, sl)                    # BUY
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 2R = 40080 => SL should move up to entry
    new_sl = bot._master_trend_trail(pos, bid=40080.0, ask=40080.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - entry) < 1e-6


def test_trailing_follows_50_pips_after_3r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40, pip_size 1.0
    pos = _pos(entry, sl)
    pos = pos.model_copy(update={"stop_loss": entry})  # already at BE
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 3R = 40120 => trail to high_water - 50*1.0 = 40070
    new_sl = bot._master_trend_trail(pos, bid=40120.0, ask=40120.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - 40070.0) < 1e-6


def test_no_loosening_below_2r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0
    pos = _pos(entry, sl)
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 1R only => no BE, no trail
    assert bot._master_trend_trail(pos, bid=40040.0, ask=40040.0, pip_size=1.0) is None
