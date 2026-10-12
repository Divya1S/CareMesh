"""GeminiProvider request and response mapping, no network involved.

httpx.MockTransport plays the Gemini REST API so the adapter's payload
building, parsing, tool mapping, and streaming are covered at zero cost.
"""

import json

import httpx
import pytest

from app.application.ai.types import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    StreamDelta,
    ToolCall,
    ToolDef,
)
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


def _provider(handler, **options) -> GeminiProvider:
    options.setdefault("retry_base_seconds", 0.0)
    return GeminiProvider(api_key="test-key", transport=httpx.MockTransport(handler), **options)


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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def test_stream_yields_deltas_then_a_response_with_usage() -> None:
    body = _sse({"candidates": [{"content": {"parts": [{"text": "Try a "}]}}]}) + _sse(
        {
            "candidates": [{"content": {"parts": [{"text": "routine."}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 9},
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "streamGenerateContent" in str(request.url)
        assert request.url.params["alt"] == "sse"
        return httpx.Response(200, content=body.encode())

    items = [item async for item in _provider(handler).stream(_request())]
    assert [item.text for item in items[:-1] if isinstance(item, StreamDelta)] == [
        "Try a ",
        "routine.",
    ]
    final = items[-1]
    assert isinstance(final, LLMResponse)
    assert final.text == "Try a routine." and final.finish_reason == "STOP"
    assert final.input_tokens == 7 and final.output_tokens == 9


async def test_streamed_function_call_arrives_on_the_response() -> None:
    body = _sse(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "search_resources",
                                    "args": {"query": "sleep"},
                                }
                            }
                        ]
                    }
                }
            ]
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    items = [item async for item in _provider(handler).stream(_request())]
    assert len(items) == 1 and isinstance(items[0], LLMResponse)
    assert items[0].tool_calls == [
        ToolCall(id="search_resources-0", name="search_resources", arguments={"query": "sleep"})
    ]


async def test_safety_blocked_answer_raises_instead_of_returning_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]},
        )

    with pytest.raises(RuntimeError, match="SAFETY"):
        await _provider(handler).complete(_request())


async def test_truncated_answer_reports_its_finish_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "Try a"}]}, "finishReason": "MAX_TOKENS"}
                ]
            },
        )

    response = await _provider(handler).complete(_request())
    assert response.text == "Try a" and response.finish_reason == "MAX_TOKENS"


async def test_retryable_status_is_retried_with_backoff() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return _text_response("Second time lucky.")

    response = await _provider(handler, max_retries=1).complete(_request())
    assert response.text == "Second time lucky." and calls["n"] == 2


async def test_retries_are_bounded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    with pytest.raises(httpx.HTTPStatusError):
        await _provider(handler, max_retries=1).complete(_request())


async def test_parallel_calls_to_one_tool_get_distinct_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "search_resources",
                                        "args": {"query": "a"},
                                    }
                                },
                                {
                                    "functionCall": {
                                        "name": "search_resources",
                                        "args": {"query": "b"},
                                    }
                                },
                            ]
                        }
                    }
                ]
            },
        )

    response = await _provider(handler).complete(_request())
    assert [c.id for c in response.tool_calls] == ["search_resources-0", "search_resources-1"]


async def test_assistant_tool_call_turn_is_sent_with_its_real_arguments() -> None:
    """A faithful transcript: the model's own call with the arguments it
    chose, then every result for that turn grouped in one user turn."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _text_response("Here is what I found.")

    calls = [
        ToolCall(id="search_resources-0", name="search_resources", arguments={"query": "sleep"}),
        ToolCall(id="search_resources-1", name="search_resources", arguments={"query": "exams"}),
    ]
    messages = [
        LLMMessage(role="user", content="Any sleep tips?"),
        LLMMessage(role="assistant", content="", tool_calls=calls),
        LLMMessage(role="tool", content="guide one", tool_call_id="search_resources-0"),
        LLMMessage(role="tool", content="guide two", tool_call_id="search_resources-1"),
    ]
    await _provider(handler).complete(_request(messages=messages))

    contents = seen["body"]["contents"]
    assert contents[1]["role"] == "model"
    assert [p["functionCall"]["args"] for p in contents[1]["parts"]] == [
        {"query": "sleep"},
        {"query": "exams"},
    ]
    assert contents[2]["role"] == "user"
    assert [p["functionResponse"]["response"]["result"] for p in contents[2]["parts"]] == [
        "guide one",
        "guide two",
    ]
    assert len(contents) == 3
