"""Real Gemini adapter over the REST API, plain httpx, no vendor SDK.

The only component in the project that can spend money, and only when a
key is configured; the free tier (no billing attached) costs nothing.
Responses carry simulated=False, so every SIMULATED label in the UI and
audit trail correctly disappears when this provider answers.

One pooled HTTP client lives for the provider's lifetime (the app builds
the provider once); retryable statuses (429, 5xx) are retried with jitter;
a safety blocked answer raises instead of returning an empty reply; and a
truncated answer is reported through finish_reason so the gateway can log
it.
"""

import asyncio
import json
import random
from collections.abc import AsyncGenerator, AsyncIterator

import httpx

from app.application.ai.types import LLMRequest, LLMResponse, StreamDelta, ToolCall

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-flash-latest"
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
# Finish reasons that mean the model was stopped from answering.
BLOCKING_FINISH_REASONS = frozenset({"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"})


class GeminiProvider:
    name = "gemini"
    simulated = False

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        max_retries: int = 2,
        retry_base_seconds: float = 0.5,
    ) -> None:
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=gemini requires LLM_API_KEY")
        self.model_name = model
        self._max_retries = max_retries
        self._retry_base = retry_base_seconds
        # The key travels in a header, never in the URL, so it cannot land
        # in access logs.
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"x-goog-api-key": api_key},
            timeout=60.0,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = response.headers.get("retry-after") if response is not None else None
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), 10.0)
        return self._retry_base * (2**attempt) + random.uniform(0, self._retry_base / 2)

    def _payload(self, request: LLMRequest) -> dict:
        system = next((m.content for m in request.messages if m.role == "system"), None)
        contents: list[dict] = []
        names_by_call_id: dict[str, str] = {}
        pending_responses: list[dict] = []

        def flush_responses() -> None:
            # Gemini wants every functionResponse for one model turn in a
            # single following user turn.
            if pending_responses:
                contents.append({"role": "user", "parts": list(pending_responses)})
                pending_responses.clear()

        for message in request.messages:
            if message.role == "system":
                continue
            if message.role == "tool":
                call_id = message.tool_call_id or "tool"
                name = names_by_call_id.get(call_id)
                if name is None:
                    # A result without its call turn (legacy transcripts):
                    # reconstruct the call so the pairing is valid.
                    flush_responses()
                    name = call_id
                    contents.append(
                        {"role": "model", "parts": [{"functionCall": {"name": name, "args": {}}}]}
                    )
                pending_responses.append(
                    {"functionResponse": {"name": name, "response": {"result": message.content}}}
                )
                continue
            flush_responses()
            if message.role == "assistant":
                parts: list[dict] = []
                if message.content:
                    parts.append({"text": message.content})
                for call in message.tool_calls:
                    names_by_call_id[call.id] = call.name
                    parts.append({"functionCall": {"name": call.name, "args": call.arguments}})
                if parts:  # Gemini rejects a turn with no parts
                    contents.append({"role": "model", "parts": parts})
                continue
            contents.append({"role": "user", "parts": [{"text": message.content}]})
        flush_responses()

        payload: dict = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": request.max_output_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if request.response_schema is not None:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if request.tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        }
                        for tool in request.tools
                    ]
                }
            ]
        return payload

    def _response(
        self,
        text_parts: list[str],
        tool_calls: list[ToolCall],
        usage: dict,
        finish_reason: str | None,
    ) -> LLMResponse:
        text = "".join(text_parts).strip()
        if finish_reason in BLOCKING_FINISH_REASONS and not text and not tool_calls:
            raise RuntimeError(f"Gemini blocked the response: {finish_reason}")
        return LLMResponse(
            text=text,
            model=self.model_name,
            provider=self.name,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            # Free tier key with no billing attached: genuinely zero. A paid
            # deployment would compute from a pricing table here.
            cost_usd=0.0,
            simulated=False,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    @staticmethod
    def _tool_call(call: dict, index: int) -> ToolCall:
        # Gemini has no call ids; name plus position keeps parallel calls
        # to the same tool apart.
        return ToolCall(
            id=f"{call['name']}-{index}", name=call["name"], arguments=call.get("args") or {}
        )

    @staticmethod
    def _blocked_prompt(data: dict) -> str | None:
        return (data.get("promptFeedback") or {}).get("blockReason")

    def _parse(self, data: dict) -> LLMResponse:
        candidates = data.get("candidates") or []
        if not candidates:
            reason = self._blocked_prompt(data) or "no candidates"
            raise RuntimeError(f"Gemini returned no answer: {reason}")
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                tool_calls.append(self._tool_call(part["functionCall"], len(tool_calls)))
        return self._response(
            text_parts, tool_calls, data.get("usageMetadata") or {}, candidate.get("finishReason")
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._payload(request)
        path = f"/models/{self.model_name}:generateContent"
        for attempt in range(self._max_retries + 1):
            response = await self._client.post(path, json=payload)
            if response.status_code in RETRYABLE_STATUSES and attempt < self._max_retries:
                await asyncio.sleep(self._backoff(attempt, response))
                continue
            response.raise_for_status()
            return self._parse(response.json())
        raise RuntimeError("Gemini retry loop exhausted")  # pragma: no cover

    async def stream(self, request: LLMRequest) -> AsyncGenerator[StreamDelta | LLMResponse]:
        payload = self._payload(request)
        path = f"/models/{self.model_name}:streamGenerateContent"
        for attempt in range(self._max_retries + 1):
            delay: float | None = None
            async with self._client.stream(
                "POST", path, params={"alt": "sse"}, json=payload
            ) as response:
                if response.status_code in RETRYABLE_STATUSES and attempt < self._max_retries:
                    delay = self._backoff(attempt, response)
                else:
                    response.raise_for_status()
                    async for item in self._read_stream(response):
                        yield item
                    return
            if delay is not None:
                await asyncio.sleep(delay)

    async def _read_stream(
        self, response: httpx.Response
    ) -> AsyncIterator[StreamDelta | LLMResponse]:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage: dict = {}
        finish_reason: str | None = None
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            chunk = json.loads(line[6:])
            blocked = self._blocked_prompt(chunk)
            if blocked:
                raise RuntimeError(f"Gemini returned no answer: {blocked}")
            usage = chunk.get("usageMetadata") or usage
            for candidate in chunk.get("candidates") or []:
                finish_reason = candidate.get("finishReason") or finish_reason
                for part in (candidate.get("content") or {}).get("parts") or []:
                    if part.get("text"):
                        text_parts.append(part["text"])
                        yield StreamDelta(part["text"])
                    elif "functionCall" in part:
                        tool_calls.append(self._tool_call(part["functionCall"], len(tool_calls)))
        yield self._response(text_parts, tool_calls, usage, finish_reason)
