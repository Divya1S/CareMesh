"""Real Gemini adapter over the REST API, plain httpx, no vendor SDK.

The only component in the project that can spend money, and only when a
key is configured; the free tier (no billing attached) costs nothing.
Responses carry simulated=False, so every SIMULATED label in the UI and
audit trail correctly disappears when this provider answers.
"""

import json
from collections.abc import AsyncIterator

import httpx

from app.application.ai.types import LLMRequest, LLMResponse, ToolCall

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-flash-latest"


class GeminiProvider:
    name = "gemini"
    simulated = False

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=gemini requires LLM_API_KEY")
        self._api_key = api_key
        self.model_name = model
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"x-goog-api-key": self._api_key},
            timeout=60.0,
            transport=self._transport,
        )

    def _payload(self, request: LLMRequest) -> dict:
        system = next((m.content for m in request.messages if m.role == "system"), None)
        contents: list[dict] = []
        for message in request.messages:
            if message.role == "system":
                continue
            if message.role == "tool":
                # Gemini pairs a functionResponse with a preceding model
                # functionCall turn; the gateway keeps only tool results, so
                # the call turn is reconstructed (arguments are not needed
                # for the model to read the result).
                tool_name = message.tool_call_id or "tool"
                contents.append(
                    {"role": "model", "parts": [{"functionCall": {"name": tool_name, "args": {}}}]}
                )
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": {"result": message.content},
                                }
                            }
                        ],
                    }
                )
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})

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

    def _parse(self, data: dict) -> LLMResponse:
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise RuntimeError(f"Gemini returned no answer: {reason}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                call = part["functionCall"]
                tool_calls.append(
                    ToolCall(id=call["name"], name=call["name"], arguments=call.get("args", {}))
                )
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text="".join(text_parts).strip(),
            model=self.model_name,
            provider=self.name,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            # Free tier key with no billing attached: genuinely zero. A paid
            # deployment would compute from a pricing table here.
            cost_usd=0.0,
            simulated=False,
            tool_calls=tool_calls,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        async with self._client() as client:
            response = await client.post(
                f"/models/{self.model_name}:generateContent", json=self._payload(request)
            )
            response.raise_for_status()
            return self._parse(response.json())

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        async with (
            self._client() as client,
            client.stream(
                "POST",
                f"/models/{self.model_name}:streamGenerateContent",
                params={"alt": "sse"},
                json=self._payload(request),
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = json.loads(line[6:])
                for candidate in chunk.get("candidates") or []:
                    for part in (candidate.get("content") or {}).get("parts") or []:
                        if part.get("text"):
                            yield part["text"]
