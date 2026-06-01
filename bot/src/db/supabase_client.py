import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from src.models.position import Position
from src.models.regime import RegimeState
from src.models.signal import Signal

log = logging.getLogger(__name__)

_RESET_ERRORS = ("10054", "10053", "ConnectionReset", "forcibly closed", "BrokenPipe",
                 "Server disconnected", "EOF", "timed out", "UNEXPECTED_EOF", "10060")


class SupabaseLogger:
    def __init__(self, client: Any):
        self._client = client

    def log_signal(self, signal: Signal, executed: bool,
                   ai_decision: Optional[str] = None,
                   ai_reasoning: Optional[str] = None) -> None:
        self._safe_insert("signals", {
            "instrument": signal.instrument,
            "direction": signal.direction.value,
            "confidence": signal.confidence,
            "regime": signal.regime.value,
            "strategy": signal.strategy,
            "ai_decision": ai_decision,
            "ai_reasoning": ai_reasoning,
            "executed": executed,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    def upsert_position(self, position: Position) -> None:
        self._safe_upsert("positions", {
            "ticket": position.ticket,
            "instrument": position.instrument,
            "direction": position.direction.value,
            "entry_price": position.entry_price,
            "current_price": position.current_price,
            "volume": position.volume,
            "profit": position.profit,
            "stop_loss": position.stop_loss,
            "take_profit": position.take_profit,
            "opened_at": position.opened_at.isoformat(),
            "strategy": position.strategy,
            "regime": position.regime.value,
        }, on_conflict="ticket")

    def record_trade(self, **fields: Any) -> None:
        self._safe_insert("trades", fields)

    def list_position_tickets(self) -> set[int]:
        """Tickets currently stored in the positions table.

        Returns an empty set on failure so callers (startup reconciliation)
        delete nothing rather than acting on partial data.
        """
        try:
            rows = self._client.table("positions").select("ticket").execute().data
            return {int(r["ticket"]) for r in rows}
        except Exception as e:
            log.warning(f"Supabase read failed (positions): {e}")
            return set()

    def delete_position(self, ticket: int) -> None:
        for attempt in range(2):
            try:
                self._client.table("positions").delete().eq("ticket", ticket).execute()
                return
            except Exception as e:
                if attempt == 0 and any(tag in str(e) for tag in _RESET_ERRORS):
                    time.sleep(1.0)   # connection was reset — brief pause then retry
                    continue
                log.warning(f"Supabase delete failed (positions #{ticket}): {e}")
                return

    def snapshot_regime(self, state: RegimeState) -> None:
        self._safe_insert("regime_snapshots", {
            "instrument": state.instrument,
            "regime": state.regime.value,
            "adx": state.indicators.get("adx"),
            "bb_width": state.indicators.get("bb_width"),
            "confidence": state.confidence,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })

    def update_bot_status(self, status: str, error: Optional[str] = None,
                          uptime: Optional[int] = None,
                          balance: Optional[float] = None,
                          equity: Optional[float] = None,
                          float_pnl: Optional[float] = None) -> None:
        payload: dict = {
            "id": 1,
            "status": status,
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "error_message": error,
            "uptime_seconds": uptime,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if balance   is not None: payload["balance"]   = round(balance,   2)
        if equity    is not None: payload["equity"]    = round(equity,    2)
        if float_pnl is not None: payload["float_pnl"] = round(float_pnl, 2)
        for attempt in range(2):
            try:
                self._client.table("bot_status").upsert(payload).execute()
                return
            except Exception as e:
                err = str(e)
                # Retry once on TCP reset before giving up
                if attempt == 0 and any(tag in err for tag in _RESET_ERRORS):
                    time.sleep(1.0)
                    continue
                # If the balance columns don't exist yet (migration 003 not run),
                # fall back silently to a write without them.
                if "balance" in err or "equity" in err or "float_pnl" in err:
                    for key in ("balance", "equity", "float_pnl"):
                        payload.pop(key, None)
                    try:
                        self._client.table("bot_status").upsert(payload).execute()
                    except Exception as e2:
                        log.warning(f"Supabase write failed (bot_status): {e2}")
                else:
                    log.warning(f"Supabase write failed (bot_status): {err}")
                return

    def _safe_insert(self, table: str, payload: dict) -> None:
        for attempt in range(2):
            try:
                self._client.table(table).insert(payload).execute()
                return
            except Exception as e:
                if attempt == 0 and any(tag in str(e) for tag in _RESET_ERRORS):
                    time.sleep(1.0)   # connection was reset — brief pause then retry
                    continue
                log.warning(f"Supabase write failed ({table}): {e}")
                return

    def _safe_upsert(self, table: str, payload: dict, on_conflict: str = "id") -> None:
        for attempt in range(2):
            try:
                self._client.table(table).upsert(payload, on_conflict=on_conflict).execute()
                return
            except Exception as e:
                if attempt == 0 and any(tag in str(e) for tag in _RESET_ERRORS):
                    time.sleep(1.0)
                    continue
                log.warning(f"Supabase write failed ({table}): {e}")
                return
