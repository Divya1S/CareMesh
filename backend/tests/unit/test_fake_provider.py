import pytest
from pydantic import BaseModel

from app.application.ai.types import LLMMessage, LLMRequest
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
