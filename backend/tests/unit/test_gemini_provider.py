"""GeminiProvider request and response mapping, no network involved.

httpx.MockTransport plays the Gemini REST API so the adapter's payload
building, parsing, tool mapping, and streaming are covered at zero cost.
"""

import json

import httpx
import pytest

from app.application.ai.types import LLMMessage, LLMRequest, ToolDef
from app.infrastructure.ai.gemini_provider import GeminiProvider


def _request(**overrides) -> LLMRequest:
    defaults = dict(
        messages=[
            LLMMessage(role="system", content="You are Dira."),
            LLMMessage(role="user", content="I cannot sleep before exams."),
        ],
        prompt_name="dira_reply",
        prompt_version=1,
    )
    defaults.update(overrides)
    return LLMRequest(**defaults)


def _provider(handler) -> GeminiProvider:
    return GeminiProvider(api_key="test-key", transport=httpx.MockTransport(handler))


def _text_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 34},
        },
    )


async def test_complete_maps_payload_and_response() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return _text_response("Try a wind down routine.")

    response = await _provider(handler).complete(_request())

    assert "gemini-flash-latest:generateContent" in seen["url"]
    assert seen["key"] == "test-key"
    assert seen["body"]["systemInstruction"]["parts"] == [{"text": "You are Dira."}]
    assert seen["body"]["contents"] == [
        {"role": "user", "parts": [{"text": "I cannot sleep before exams."}]}
    ]
    assert response.text == "Try a wind down routine."
    assert response.simulated is False
    assert response.provider == "gemini"
    assert response.input_tokens == 12
    assert response.output_tokens == 34
    assert response.cost_usd == 0.0
    assert response.tool_calls == []


async def test_tools_declared_and_tool_calls_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"][0]["functionDeclarations"][0]["name"] == "search_resources"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "search_resources",
                                        "args": {"query": "sleep"},
                                    }
                                }
                            ],
                        }
                    }
                ],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 6},
            },
        )

    tool = ToolDef(
        name="search_resources",
        description="Search the resource library.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    response = await _provider(handler).complete(_request(tools=[tool]))

    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "search_resources"
    assert call.arguments == {"query": "sleep"}


async def test_tool_result_message_becomes_function_response_pair() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _text_response("Here is what I found.")

    messages = [
        LLMMessage(role="user", content="Any sleep tips?"),
        LLMMessage(
            role="tool", content="Sleep guide: keep a routine.", tool_call_id="search_resources"
        ),
    ]
    await _provider(handler).complete(_request(messages=messages))

    contents = seen["body"]["contents"]
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][0]["functionCall"]["name"] == "search_resources"
    assert contents[2]["role"] == "user"
    assert (
        contents[2]["parts"][0]["functionResponse"]["response"]["result"]
        == "Sleep guide: keep a routine."
    )


async def test_blocked_prompt_raises_with_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    with pytest.raises(RuntimeError, match="SAFETY"):
        await _provider(handler).complete(_request())


async def test_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    with pytest.raises(httpx.HTTPStatusError):
        await _provider(handler).complete(_request())


async def test_missing_key_fails_loudly() -> None:
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        GeminiProvider(api_key="")


async def test_stream_text_yields_sse_chunks() -> None:
    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    body = sse({"candidates": [{"content": {"parts": [{"text": "Try a "}]}}]}) + sse(
        {"candidates": [{"content": {"parts": [{"text": "routine."}]}}]}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "streamGenerateContent" in str(request.url)
        assert request.url.params["alt"] == "sse"
        return httpx.Response(200, content=body.encode())

    chunks = [c async for c in _provider(handler).stream_text(_request())]
    assert chunks == ["Try a ", "routine."]
