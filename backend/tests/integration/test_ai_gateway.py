"""Gateway tests: every call is logged with the simulated flag, validation
retries then fails typed, and timeouts are recorded. Needs Postgres."""

import asyncio

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.application.ai.gateway import (
    AIGateway,
    AIProviderError,
    AITimeoutError,
    AIValidationError,
)
from app.application.ai.tools import Tool, ToolResult
from app.application.ai.types import LLMMessage, LLMResponse, ToolCall, ToolDef
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


class ScriptedProvider:
    """Returns the scripted responses in order, recording every request."""

    name = "scripted"
    model_name = "scripted-1"
    simulated = True

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def _reply(self, text="", tool_calls=()):
        return LLMResponse(
            text=text,
            model=self.model_name,
            provider=self.name,
            input_tokens=3,
            output_tokens=2,
            cost_usd=0.0,
            simulated=True,
            tool_calls=list(tool_calls),
        )

    async def complete(self, request):
        self.requests.append(request)
        item = self.responses.pop(0)
        return item(self, request) if callable(item) else self._reply(**item)


def scripted_gateway(app, provider) -> AIGateway:
    return AIGateway(provider, SqlAIRequestLog(app.state.session_factory), timeout_seconds=5.0)


async def test_validation_retry_feeds_the_error_back(app, seeded):
    """The retry is not a blind resample: the model is told what was wrong.
    This provider only answers correctly once it sees that feedback."""

    def corrected(provider, request):
        last = request.messages[-1]
        assert last.role == "user" and "did not match" in last.content
        assert "severity" in last.content
        return provider._reply(
            text='{"category": "none", "severity": 0, "confidence": 0.5, "evidence": ""}'
        )

    provider = ScriptedProvider({"text": '{"category": "none", "severity": 99}'}, corrected)
    result = await scripted_gateway(app, provider).complete(
        prompt_name="risk_signal",
        user_messages=[LLMMessage("user", "hello")],
        organization_id=seeded["org_a"].id,
        response_schema=RiskDraft,
    )
    assert isinstance(result.structured, RiskDraft)
    assert len(provider.requests) == 2
    row = await latest_log(app)
    assert row.status == "ok" and row.validation_ok is True
    assert row.input_tokens == 6, "usage is summed across both attempts"


def _tool(name: str, runs: list, mutates: bool = False) -> Tool:
    async def run(arguments: dict) -> ToolResult:
        runs.append((name, arguments))
        return ToolResult(content=f"{name} result", summary=f"ran {name}")

    return Tool(
        definition=ToolDef(
            name=name,
            description=name,
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        run=run,
        mutates=mutates,
    )


async def test_extra_tool_calls_are_skipped_and_the_model_is_told(app, seeded):
    runs: list = []
    provider = ScriptedProvider(
        {
            "tool_calls": [
                ToolCall(id="c1", name="search", arguments={"query": "a"}),
                ToolCall(id="c2", name="search", arguments={"query": "b"}),
            ]
        },
        {"text": "done"},
    )
    result = await scripted_gateway(app, provider).complete(
        prompt_name="dira_reply",
        user_messages=[LLMMessage("user", "hi")],
        organization_id=seeded["org_a"].id,
        tools=[_tool("search", runs)],
    )
    assert result.text == "done"
    assert runs == [("search", {"query": "a"})], "only one call runs per round"
    second_request = provider.requests[1]
    assistant_turn = next(m for m in second_request.messages if m.role == "assistant")
    assert [c.id for c in assistant_turn.tool_calls] == ["c1", "c2"], "the transcript is faithful"
    skipped = next(m for m in second_request.messages if m.tool_call_id == "c2")
    assert skipped.content.startswith("Skipped")
    row = await latest_log(app)
    assert [c.get("skipped", False) for c in row.tool_calls] == [False, True]


async def test_invalid_tool_arguments_never_reach_the_handler(app, seeded):
    runs: list = []
    provider = ScriptedProvider(
        {"tool_calls": [ToolCall(id="c1", name="search", arguments={"query": 42})]},
        {"text": "ok without it"},
    )
    await scripted_gateway(app, provider).complete(
        prompt_name="dira_reply",
        user_messages=[LLMMessage("user", "hi")],
        organization_id=seeded["org_a"].id,
        tools=[_tool("search", runs)],
    )
    assert runs == []
    rejection = next(m for m in provider.requests[1].messages if m.role == "tool")
    assert "Invalid arguments" in rejection.content


async def test_failed_mutating_tool_is_audited_as_a_provider_error(app, seeded):
    async def boom(arguments: dict) -> ToolResult:
        raise RuntimeError("write failed")

    tool = Tool(
        definition=ToolDef(
            name="book", description="book", parameters={"type": "object", "properties": {}}
        ),
        run=boom,
        mutates=True,
    )
    provider = ScriptedProvider({"tool_calls": [ToolCall(id="c1", name="book", arguments={})]})
    with pytest.raises(AIProviderError):
        await scripted_gateway(app, provider).complete(
            prompt_name="dira_reply",
            user_messages=[LLMMessage("user", "hi")],
            organization_id=seeded["org_a"].id,
            tools=[tool],
        )
    row = await latest_log(app)
    assert row.status == "provider_error" and row.error_type == "AIProviderError"


async def test_client_disconnect_mid_stream_is_audited_as_cancelled(app, seeded):
    gateway = make_gateway(app)
    stream = gateway.stream_reply(
        prompt_name="dira_reply",
        user_messages=[LLMMessage("user", "I feel sad")],
        organization_id=seeded["org_a"].id,
    )
    assert (await anext(stream))["type"] == "start"
    assert (await anext(stream))["type"] == "delta"
    await stream.aclose()  # closes the generator like a disconnect does
    # The cancellation path cannot await inside the dying task, so the
    # write is detached; wait for it like the app's shutdown does.
    await AIGateway.flush_detached_log_writes()
    row = await latest_log(app)
    assert row.status == "cancelled" and row.error_type == "ClientDisconnected"
    assert row.response_text is None


class StallingStreamProvider:
    """Streams one delta, then never finishes: a provider that hangs mid
    reply. The round deadline must fire as a timeout."""

    name = "stalling"
    model_name = "stalling-1"
    simulated = True

    async def complete(self, request):
        raise AssertionError("stream path only")

    async def stream(self, request):
        from app.application.ai.types import StreamDelta

        yield StreamDelta("first ")
        await asyncio.sleep(3600)


async def test_stream_that_stalls_after_a_delta_times_out(app, seeded):
    gateway = AIGateway(
        StallingStreamProvider(), SqlAIRequestLog(app.state.session_factory), timeout_seconds=0.3
    )
    events = []
    with pytest.raises(AITimeoutError):
        async for event in gateway.stream_reply(
            prompt_name="dira_reply",
            user_messages=[LLMMessage("user", "hi")],
            organization_id=seeded["org_a"].id,
        ):
            events.append(event["type"])
    assert events == ["start", "delta"]
    row = await latest_log(app)
    assert row.status == "timeout"
