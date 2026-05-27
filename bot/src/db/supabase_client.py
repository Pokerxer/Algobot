import logging
from datetime import datetime, timezone
from typing import Any, Optional
from src.models.position import Position
from src.models.regime import RegimeState
from src.models.signal import Signal

log = logging.getLogger(__name__)


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
                          uptime: Optional[int] = None) -> None:
        try:
            self._client.table("bot_status").upsert({
                "id": 1,
                "status": status,
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                "error_message": error,
                "uptime_seconds": uptime,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            log.warning(f"Supabase write failed (bot_status): {e}")

    def _safe_insert(self, table: str, payload: dict) -> None:
        try:
            self._client.table(table).insert(payload).execute()
        except Exception as e:
            log.warning(f"Supabase write failed ({table}): {e}")

    def _safe_upsert(self, table: str, payload: dict, on_conflict: str = "id") -> None:
        try:
            self._client.table(table).upsert(payload, on_conflict=on_conflict).execute()
        except Exception as e:
            log.warning(f"Supabase write failed ({table}): {e}")
