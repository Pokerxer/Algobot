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


def test_list_position_tickets_returns_ticket_set():
    client, chain = _fake_client()
    chain.select.return_value.execute.return_value = MagicMock(
        data=[{"ticket": 111}, {"ticket": 222}])
    assert SupabaseLogger(client).list_position_tickets() == {111, 222}
    client.table.assert_called_with("positions")


def test_list_position_tickets_returns_empty_set_on_failure():
    # On a read failure, return empty set so reconciliation deletes nothing.
    client = MagicMock()
    client.table.side_effect = RuntimeError("network down")
    assert SupabaseLogger(client).list_position_tickets() == set()


def test_delete_position_deletes_by_ticket():
    client, chain = _fake_client()
    SupabaseLogger(client).delete_position(123)
    client.table.assert_called_with("positions")
    chain.delete.return_value.eq.assert_called_with("ticket", 123)


def test_record_trade_retries_after_connection_aborted_then_succeeds(caplog):
    client, chain = _fake_client()
    chain.upsert.return_value.execute.side_effect = [
        ConnectionError("('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"),
        MagicMock(data=[{"id": 1}]),
    ]
    SupabaseLogger(client).record_trade(ticket=1, instrument="EURUSD")
    assert chain.upsert.return_value.execute.call_count == 2
    assert "Supabase write failed" not in caplog.text


def test_upsert_signal_evaluation_upserts_by_instrument():
    from src.insight.evaluator import Evaluation
    client, chain = _fake_client()
    ev = Evaluation("EURUSDm", "RANGING", True, "mean_reversion",
                    "no_setup", "price mid-band", 0.34, {"pct_b": 0.34})
    SupabaseLogger(client).upsert_signal_evaluation(ev)
    client.table.assert_called_with("signal_evaluations")
    payload = chain.upsert.call_args[0][0]
    assert payload["instrument"] == "EURUSDm"
    assert payload["status"] == "no_setup"
    assert payload["detail"] == {"pct_b": 0.34}
    assert chain.upsert.call_args.kwargs["on_conflict"] == "instrument"
