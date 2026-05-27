from unittest.mock import MagicMock
from src.db.supabase_client import SupabaseLogger
from src.models.signal import Signal, Direction
from src.models.regime import Regime


def _fake_client():
    client = MagicMock()
    chain = MagicMock()
    client.table.return_value = chain
    chain.insert.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
    chain.upsert.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
    return client, chain


def test_log_signal_inserts_into_signals_table():
    client, chain = _fake_client()
    SupabaseLogger(client).log_signal(
        Signal(instrument="EURUSD", direction=Direction.BUY,
               entry_price=1.085, stop_loss=1.082, take_profit=1.091,
               confidence=0.7, regime=Regime.TRENDING_UP, strategy="momentum"),
        executed=True,
    )
    client.table.assert_called_with("signals")
    payload = chain.insert.call_args[0][0]
    assert payload["instrument"] == "EURUSD"
    assert payload["executed"] is True


def test_update_bot_status_upserts():
    client, chain = _fake_client()
    SupabaseLogger(client).update_bot_status(status="OK", error=None)
    client.table.assert_called_with("bot_status")
    chain.upsert.assert_called_once()


def test_failures_swallowed_not_raised(caplog):
    client = MagicMock()
    client.table.side_effect = RuntimeError("network down")
    SupabaseLogger(client).update_bot_status(status="ERROR", error="x")
    assert "Supabase write failed" in caplog.text
