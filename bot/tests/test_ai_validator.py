import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from src.ai.validator import AIDecision, AIValidator
from src.config.schema import AIConfig
from src.models.regime import Regime, RegimeState
from src.models.signal import Direction, Signal


def _cfg(**kwargs) -> AIConfig:
    defaults = dict(enabled=True, confidence_threshold=0.6, max_calls_per_day=10,
                    timeout_seconds=5, model="claude-sonnet-4-6")
    return AIConfig(**{**defaults, **kwargs})


def _signal(confidence=0.8) -> Signal:
    return Signal(
        instrument="EURUSD", direction=Direction.BUY,
        entry_price=1.1000, stop_loss=1.0950, take_profit=1.1100,
        confidence=confidence, regime=Regime.TRENDING_UP, strategy="momentum",
    )


def _state() -> RegimeState:
    return RegimeState(
        instrument="EURUSD", regime=Regime.TRENDING_UP, confidence=0.8,
        indicators={"adx": 30.5, "bb_width": 0.012},
    )


def _mock_response(payload: dict) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(payload))]
    return msg


@pytest.mark.asyncio
async def test_approve_response():
    validator = AIValidator(_cfg())
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_response(
        {"action": "APPROVE", "reasoning": "good r/r", "stop_loss": None, "take_profit": None}
    )
    validator._client = mock_client
    decision = await validator.validate(_signal(), _state(), balance=500.0)
    assert decision.action == "APPROVE"
    assert "good r/r" in decision.reasoning


@pytest.mark.asyncio
async def test_veto_response():
    validator = AIValidator(_cfg())
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_response(
        {"action": "VETO", "reasoning": "news risk", "stop_loss": None, "take_profit": None}
    )
    validator._client = mock_client
    decision = await validator.validate(_signal(), _state(), balance=500.0)
    assert decision.action == "VETO"


@pytest.mark.asyncio
async def test_modify_response():
    validator = AIValidator(_cfg())
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_response(
        {"action": "MODIFY", "reasoning": "tighten sl", "stop_loss": 1.0960, "take_profit": 1.1100}
    )
    validator._client = mock_client
    decision = await validator.validate(_signal(), _state(), balance=500.0)
    assert decision.action == "MODIFY"
    assert decision.stop_loss == pytest.approx(1.0960)
    assert decision.take_profit == pytest.approx(1.1100)


@pytest.mark.asyncio
async def test_skips_when_disabled():
    validator = AIValidator(_cfg(enabled=False))
    decision = await validator.validate(_signal(), _state(), balance=500.0)
    assert decision.action == "APPROVE"
    assert "fallback" in decision.reasoning


@pytest.mark.asyncio
async def test_skips_low_confidence():
    validator = AIValidator(_cfg(confidence_threshold=0.9))
    decision = await validator.validate(_signal(confidence=0.7), _state(), balance=500.0)
    assert decision.action == "APPROVE"
    assert "below threshold" in decision.reasoning


@pytest.mark.asyncio
async def test_falls_back_on_api_error():
    validator = AIValidator(_cfg())
    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = Exception("timeout")
    validator._client = mock_client
    decision = await validator.validate(_signal(), _state(), balance=500.0)
    assert decision.action == "APPROVE"
    assert "fallback" in decision.reasoning


@pytest.mark.asyncio
async def test_falls_back_on_malformed_json():
    validator = AIValidator(_cfg())
    mock_client = AsyncMock()
    msg = MagicMock()
    msg.content = [MagicMock(text="not json at all")]
    mock_client.messages.create.return_value = msg
    validator._client = mock_client
    decision = await validator.validate(_signal(), _state(), balance=500.0)
    assert decision.action == "APPROVE"
    assert "fallback" in decision.reasoning


@pytest.mark.asyncio
async def test_daily_call_limit():
    validator = AIValidator(_cfg(max_calls_per_day=2))
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_response(
        {"action": "APPROVE", "reasoning": "ok", "stop_loss": None, "take_profit": None}
    )
    validator._client = mock_client

    await validator.validate(_signal(), _state(), balance=500.0)
    await validator.validate(_signal(), _state(), balance=500.0)
    # third call should hit the limit and fall back without calling the API
    decision = await validator.validate(_signal(), _state(), balance=500.0)
    assert decision.action == "APPROVE"
    assert "fallback" in decision.reasoning
    assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_increments_call_counter():
    validator = AIValidator(_cfg())
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_response(
        {"action": "APPROVE", "reasoning": "ok", "stop_loss": None, "take_profit": None}
    )
    validator._client = mock_client
    assert validator._calls_today == 0
    await validator.validate(_signal(), _state(), balance=500.0)
    assert validator._calls_today == 1
