import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

import anthropic

from src.config.schema import AIConfig
from src.models.regime import RegimeState
from src.models.signal import Signal

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a disciplined quantitative trading analyst reviewing candidate trade signals.
Your job is to approve, veto, or modify (SL/TP only) signals produced by a rule-based engine.

Rules you must follow:
- Only output valid JSON — no markdown, no prose outside the JSON object.
- You may only modify stop_loss and take_profit; never change direction or entry price.
- Veto only when you have a specific, articulable reason (e.g. news risk, obvious regime mismatch,
  risk/reward below 1.5:1). Do not veto out of excessive caution.
- If uncertain, APPROVE — the rule-based risk manager has already applied hard limits.
- Fail fast: if you cannot form a clear view, output APPROVE.

Output format (strict JSON, one object, no other text):
{"action": "APPROVE" | "VETO" | "MODIFY", "reasoning": "<concise reason>", \
"stop_loss": <float or null>, "take_profit": <float or null>}
"""


@dataclass
class AIDecision:
    action: Literal["APPROVE", "VETO", "MODIFY"]
    reasoning: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


_FALLBACK = AIDecision(action="APPROVE", reasoning="fallback: AI validation unavailable")


class AIValidator:
    def __init__(self, config: AIConfig, client: Optional[anthropic.AsyncAnthropic] = None):
        self._cfg = config
        self._client = client or anthropic.AsyncAnthropic()
        self._calls_today: int = 0
        self._call_date: date = date.today()

    async def validate(
        self, signal: Signal, state: RegimeState, balance: float
    ) -> AIDecision:
        if not self._cfg.enabled:
            return _FALLBACK

        if signal.confidence < self._cfg.confidence_threshold:
            return AIDecision(
                action="APPROVE",
                reasoning=f"confidence {signal.confidence:.2f} below threshold "
                          f"{self._cfg.confidence_threshold}; skipping AI review",
            )

        self._reset_daily_counter()
        if self._calls_today >= self._cfg.max_calls_per_day:
            log.warning("AI daily call limit reached (%d); falling back", self._cfg.max_calls_per_day)
            return _FALLBACK

        prompt = self._build_prompt(signal, state, balance)
        try:
            response = await self._client.messages.create(
                model=self._cfg.model,
                max_tokens=256,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                timeout=self._cfg.timeout_seconds,
            )
            self._calls_today += 1
            return self._parse(response.content[0].text)
        except Exception as exc:
            log.warning("AI validation failed (%s); falling back to approve", exc)
            return _FALLBACK

    def _reset_daily_counter(self) -> None:
        today = date.today()
        if today != self._call_date:
            self._calls_today = 0
            self._call_date = today

    @staticmethod
    def _build_prompt(signal: Signal, state: RegimeState, balance: float) -> str:
        rr = abs(signal.take_profit - signal.entry_price) / max(
            abs(signal.stop_loss - signal.entry_price), 1e-8
        )
        indicators = ", ".join(
            f"{k}={v:.4f}" for k, v in state.indicators.items() if v is not None
        )
        return (
            f"Instrument: {signal.instrument}\n"
            f"Direction: {signal.direction.value}\n"
            f"Entry: {signal.entry_price:.5f}  SL: {signal.stop_loss:.5f}  "
            f"TP: {signal.take_profit:.5f}  R/R: {rr:.2f}\n"
            f"Regime: {state.regime.value} (confidence {state.confidence:.2f})\n"
            f"Indicators: {indicators or 'n/a'}\n"
            f"Strategy: {signal.strategy}\n"
            f"Account balance: ${balance:.2f}\n\n"
            "Should this trade be placed? Respond with JSON only."
        )

    @staticmethod
    def _parse(text: str) -> AIDecision:
        try:
            raw = json.loads(text.strip())
            action = raw["action"]
            if action not in ("APPROVE", "VETO", "MODIFY"):
                raise ValueError(f"Unknown action: {action}")
            return AIDecision(
                action=action,
                reasoning=raw.get("reasoning", ""),
                stop_loss=raw.get("stop_loss"),
                take_profit=raw.get("take_profit"),
            )
        except Exception as exc:
            log.warning("Failed to parse AI response (%s): %r", exc, text)
            return _FALLBACK
