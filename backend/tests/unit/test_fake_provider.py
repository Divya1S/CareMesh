import pytest
from pydantic import BaseModel

from app.application.ai.types import LLMMessage, LLMRequest, LLMResponse, StreamDelta, ToolDef
from app.infrastructure.ai.factory import create_provider
from app.infrastructure.ai.fake_provider import FakeLLMProvider, FakeProviderError


def make_request(content: str, schema=None) -> LLMRequest:
    return LLMRequest(
        messages=[LLMMessage("system", "s"), LLMMessage("user", content)],
        prompt_name="dira_reply",
        prompt_version=1,
        response_schema=schema,
    )


class RiskDraft(BaseModel):
    category: str
    severity: int
    confidence: float
    evidence: str


async def test_fake_provider_is_deterministic():
    provider = FakeLLMProvider()
    first = await provider.complete(make_request("I feel sad today"))
    second = await provider.complete(make_request("I feel sad today"))
    assert first.text == second.text


async def test_every_response_is_labeled_simulated_and_free():
    response = await FakeLLMProvider().complete(make_request("hello"))
    assert response.simulated is True
    assert response.cost_usd == 0.0
    assert response.provider == "fake"


async def test_scenarios_change_the_reply():
    provider = FakeLLMProvider()
    sad = await provider.complete(make_request("I have been so sad"))
    exam = await provider.complete(make_request("my exam is coming"))
    crisis = await provider.complete(make_request("I want to hurt myself"))
    assert len({sad.text, exam.text, crisis.text}) == 3
    assert "crisis" in crisis.text.lower()


async def test_structured_output_matches_schema():
    response = await FakeLLMProvider().complete(
        make_request("I want to hurt myself", schema=RiskDraft)
    )
    draft = RiskDraft.model_validate_json(response.text)
    assert draft.category == "crisis"
    assert draft.severity == 3


async def test_injected_provider_error():
    with pytest.raises(FakeProviderError):
        await FakeLLMProvider().complete(make_request("x [[fail:error]]"))


def test_factory_defaults_and_swap():
    assert create_provider("fake").name == "fake"

    class Stub:
        name = "stub"

        async def complete(self, request):
            raise NotImplementedError

    from app.infrastructure.ai.factory import register_provider

    register_provider("stub", Stub)
    assert create_provider("stub").name == "stub"

    with pytest.raises(RuntimeError, match="not implemented"):
        create_provider("anthropic")
    with pytest.raises(RuntimeError, match="Unknown"):
        create_provider("nonsense")


async def test_stream_yields_deltas_then_the_full_response():
    items = [item async for item in FakeLLMProvider().stream(make_request("hello"))]
    assert isinstance(items[-1], LLMResponse)
    assert items[:-1] and all(isinstance(item, StreamDelta) for item in items[:-1])
    assert "".join(item.text for item in items[:-1]).strip() == items[-1].text


async def test_stream_with_a_tool_call_yields_only_the_response():
    tool = ToolDef(
        name="search_resources",
        description="search",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    request = LLMRequest(
        messages=[LLMMessage("system", "s"), LLMMessage("user", "any tips to sleep better?")],
        prompt_name="dira_reply",
        prompt_version=1,
        tools=[tool],
    )
    items = [item async for item in FakeLLMProvider().stream(request)]
    assert len(items) == 1 and isinstance(items[0], LLMResponse)
    assert items[0].tool_calls[0].name == "search_resources"


async def test_failure_markers_apply_to_any_user_message():
    """A validation retry appends feedback as the newest user message; the
    injected failure must keep failing so the retry path stays testable."""
    request = LLMRequest(
        messages=[
            LLMMessage("system", "s"),
            LLMMessage("user", "x [[fail:error]]"),
            LLMMessage("assistant", "..."),
            LLMMessage("user", "please try again"),
        ],
        prompt_name="dira_reply",
        prompt_version=1,
    )
    with pytest.raises(FakeProviderError):
        await FakeLLMProvider().complete(request)
