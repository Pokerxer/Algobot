from datetime import datetime, timezone

from src.models.position import Position
from src.models.regime import Regime
from src.models.signal import Direction


def _pos(entry, sl, tp=None, direction=Direction.BUY, ticket=1):
    return Position(
        ticket=ticket, instrument="USTECm", direction=direction,
        entry_price=entry, current_price=entry, volume=1.0, profit=0.0,
        stop_loss=sl, take_profit=tp,
        opened_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        strategy="master_trend", regime=Regime.TRENDING_UP,
    )


def _rej_pos(entry, sl, **kw):
    return _pos(entry, sl, tp=entry * 1.004, **kw)   # tp_pct_rej 0.4% => rejection ladder


def _mt_pos(entry, sl, **kw):
    return _pos(entry, sl, tp=entry * 1.008, **kw)   # tp_pct_mt 0.8% => MT ladder


def _bot():
    # Build a TradingBot without __init__; only config + caches are used here.
    from src.bot import TradingBot
    from src.config.schema import AppConfig, AccountConfig
    cfg = AppConfig(account=AccountConfig(starting_balance=1500), instruments=["USTECm"])
    bot = TradingBot.__new__(TradingBot)
    bot._cfg = cfg
    bot._mt_r_dist = {}
    bot._mt_high_water = {}
    return bot


# ── rejection-kind positions: BE at 2R, trail at 3R ──────────────────────────

def test_rej_breakeven_moves_sl_to_entry_at_2r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40
    pos = _rej_pos(entry, sl)                # BUY
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 2R = 40080 => SL should move up to entry
    new_sl = bot._master_trend_trail(pos, bid=40080.0, ask=40080.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - entry) < 1e-6


def test_rej_trailing_follows_50_pips_after_3r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40, pip_size 1.0
    pos = _rej_pos(entry, sl)
    pos = pos.model_copy(update={"stop_loss": entry})  # already at BE
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 3R = 40120 => trail to high_water - 50*1.0 = 40070
    new_sl = bot._master_trend_trail(pos, bid=40120.0, ask=40120.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - 40070.0) < 1e-6


def test_rej_trailing_persists_after_pullback():
    # Pine fidelity: once high-water reached 3R, trailing stays active even if
    # the current price pulls back below the trigger level.
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40
    pos = _rej_pos(entry, sl)
    bot._mt_r_dist[pos.ticket] = 40.0
    bot._mt_high_water[pos.ticket] = 40120.0  # earlier spike to exactly 3R
    # price now back at 2.5R => trail must still apply from high-water
    new_sl = bot._master_trend_trail(pos, bid=40100.0, ask=40100.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - 40070.0) < 1e-6


def test_rej_no_loosening_below_2r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0
    pos = _rej_pos(entry, sl)
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 1R only => no BE, no trail
    assert bot._master_trend_trail(pos, bid=40040.0, ask=40040.0, pip_size=1.0) is None


# ── MT-signal-kind positions: BE at 3R, trail at 5R ──────────────────────────

def test_mt_no_breakeven_at_2r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40
    pos = _mt_pos(entry, sl)
    bot._mt_r_dist[pos.ticket] = 40.0
    # 2R would trigger the rejection ladder but NOT the MT ladder
    assert bot._master_trend_trail(pos, bid=40080.0, ask=40080.0, pip_size=1.0) is None


def test_mt_breakeven_moves_sl_to_entry_at_3r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40
    pos = _mt_pos(entry, sl)
    bot._mt_r_dist[pos.ticket] = 40.0
    new_sl = bot._master_trend_trail(pos, bid=40120.0, ask=40120.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - entry) < 1e-6


def test_mt_no_trailing_at_4r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40
    pos = _mt_pos(entry, sl)
    pos = pos.model_copy(update={"stop_loss": entry})  # already at BE
    bot._mt_r_dist[pos.ticket] = 40.0
    # 4R: above BE threshold (SL already at entry => no change), below trail start
    assert bot._master_trend_trail(pos, bid=40160.0, ask=40160.0, pip_size=1.0) is None


def test_mt_trailing_follows_50_pips_after_5r():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40, pip_size 1.0
    pos = _mt_pos(entry, sl)
    pos = pos.model_copy(update={"stop_loss": entry})  # already at BE
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry + 5R = 40200 => trail to high_water - 50*1.0 = 40150
    new_sl = bot._master_trend_trail(pos, bid=40200.0, ask=40200.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - 40150.0) < 1e-6


def test_missing_tp_falls_back_to_rejection_ladder():
    bot = _bot()
    entry, sl = 40000.0, 39960.0            # R = 40
    pos = _pos(entry, sl, tp=None)
    bot._mt_r_dist[pos.ticket] = 40.0
    # 2R => BE under the rejection ladder (the fallback when TP is unknown)
    new_sl = bot._master_trend_trail(pos, bid=40080.0, ask=40080.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - entry) < 1e-6


def test_sell_mt_trailing_at_5r():
    bot = _bot()
    entry, sl = 40000.0, 40040.0            # SELL, R = 40
    pos = _pos(entry, sl, tp=entry * 0.992, direction=Direction.SELL)  # 0.8% => MT
    pos = pos.model_copy(update={"stop_loss": entry})  # already at BE
    bot._mt_r_dist[pos.ticket] = 40.0
    # price at entry - 5R = 39800 => trail to high_water + 50*1.0 = 39850
    new_sl = bot._master_trend_trail(pos, bid=39800.0, ask=39800.0, pip_size=1.0)
    assert new_sl is not None and abs(new_sl - 39850.0) < 1e-6
