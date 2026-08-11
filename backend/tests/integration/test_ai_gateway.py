"""Gateway tests: every call is logged with the simulated flag, validation
retries then fails typed, and timeouts are recorded. Needs Postgres."""

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.application.ai.gateway import AIGateway, AITimeoutError, AIValidationError
from app.application.ai.types import LLMMessage
from app.infrastructure.ai.fake_provider import FakeLLMProvider
from app.infrastructure.models import AIRequestRow
from app.infrastructure.repositories import SqlAIRequestLog

pytestmark = pytest.mark.integration


class RiskDraft(BaseModel):
    category: str
    severity: int = Field(ge=0, le=3)
    confidence: float = Field(ge=0, le=1)
    evidence: str


def make_gateway(app, timeout=5.0) -> AIGateway:
    return AIGateway(
        FakeLLMProvider(),
        SqlAIRequestLog(app.state.session_factory),
        timeout_seconds=timeout,
    )


async def latest_log(app) -> AIRequestRow:
    async with app.state.session_factory() as session:
        rows = (await session.scalars(select(AIRequestRow).order_by(AIRequestRow.id.desc()))).all()
    assert rows, "gateway call was not logged"
    return rows[0]


async def test_gateway_logs_success_with_simulated_flag(app, seeded):
    gateway = make_gateway(app)
    result = await gateway.complete(
        prompt_name="dira_reply",
        user_messages=[LLMMessage("user", "I feel sad")],
        organization_id=seeded["org_a"].id,
        correlation_id="corr-ai-1",
    )
    assert result.simulated is True
    assert result.text

    row = await latest_log(app)
    assert str(row.id) == result.ai_request_id
    assert row.status == "ok"
    assert row.simulated is True
    assert row.prompt_name == "dira_reply" and row.prompt_version == 1
    assert row.provider == "fake" and row.model == "fake-sim-1"
    assert row.cost_usd == 0.0
    assert row.correlation_id == "corr-ai-1"
    assert row.latency_ms > 0
    assert row.input_tokens > 0 and row.output_tokens > 0


async def test_structured_output_validated_and_returned(app, seeded):
    gateway = make_gateway(app)
    result = await gateway.complete(
        prompt_name="risk_signal",
        user_messages=[LLMMessage("user", "I want to hurt myself")],
        organization_id=seeded["org_a"].id,
        response_schema=RiskDraft,
    )
    assert isinstance(result.structured, RiskDraft)
    assert result.structured.category == "crisis"
    row = await latest_log(app)
    assert row.validation_ok is True


async def test_malformed_output_fails_typed_and_is_logged(app, seeded):
    gateway = make_gateway(app)
    with pytest.raises(AIValidationError):
        await gateway.complete(
            prompt_name="risk_signal",
            user_messages=[LLMMessage("user", "x [[fail:malformed]]")],
            organization_id=seeded["org_a"].id,
            response_schema=RiskDraft,
        )
    row = await latest_log(app)
    assert row.status == "validation_failed"
    assert row.validation_ok is False
    assert row.error_type == "ValidationError"


async def test_timeout_is_typed_and_logged(app, seeded):
    gateway = make_gateway(app, timeout=0.05)
    with pytest.raises(AITimeoutError):
        await gateway.complete(
            prompt_name="dira_reply",
            user_messages=[LLMMessage("user", "x [[fail:timeout]]")],
            organization_id=seeded["org_a"].id,
        )
    row = await latest_log(app)
    assert row.status == "timeout"


async def test_unknown_prompt_is_rejected(app, seeded):
    gateway = make_gateway(app)
    from app.application.errors import DomainValidationError

    with pytest.raises(DomainValidationError):
        await gateway.complete(
            prompt_name="not_registered",
            user_messages=[LLMMessage("user", "hi")],
            organization_id=seeded["org_a"].id,
        )
