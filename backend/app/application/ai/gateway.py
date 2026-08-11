"""The AI Gateway: the only path from business logic to any LLM.

Responsibilities here: prompt resolution, timeout, structured output
validation with one bounded retry, and logging every call, success or
failure, to the AI request log. Provider selection happens in
infrastructure; business logic only ever sees this class.
"""

import asyncio
import time
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.application.ai.prompts import get_prompt
from app.application.ai.tools import Tool, ToolResult
from app.application.ai.types import (
    AI_STATUS,
    AIRequestLogEntry,
    GatewayResult,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    ToolActivity,
)
from app.application.errors import AppError
from app.domain.ids import uuid7

# A model gets at most this many rounds of tool use before it must answer.
MAX_TOOL_ITERATIONS = 3


class AIProviderError(AppError):
    code = "ai_provider_error"
    title = "AI provider error"


class AITimeoutError(AppError):
    code = "ai_timeout"
    title = "AI provider timed out"


class AIValidationError(AppError):
    code = "ai_validation_failed"
    title = "AI output failed validation"


class LLMProvider(Protocol):
    name: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class AIRequestLog(Protocol):
    async def add(self, entry: AIRequestLogEntry) -> None: ...


class AIGateway:
    def __init__(
        self,
        provider: LLMProvider,
        log: AIRequestLog,
        *,
        timeout_seconds: float,
        validation_retries: int = 1,
    ) -> None:
        self._provider = provider
        self._log = log
        self._timeout = timeout_seconds
        self._validation_retries = validation_retries

    async def complete(
        self,
        *,
        prompt_name: str,
        user_messages: list[LLMMessage],
        organization_id: UUID,
        correlation_id: str | None = None,
        response_schema: type[BaseModel] | None = None,
        tools: Sequence[Tool] = (),
    ) -> GatewayResult:
        prompt = get_prompt(prompt_name)
        request = LLMRequest(
            messages=[LLMMessage("system", prompt.system), *user_messages],
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            response_schema=response_schema,
            tools=[tool.definition for tool in tools],
        )
        entry = AIRequestLogEntry(
            id=str(uuid7()),
            organization_id=str(organization_id),
            provider=self._provider.name,
            model="",
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            status=AI_STATUS.ok,
            simulated=False,
            validation_ok=None,
            latency_ms=0.0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            correlation_id=correlation_id,
            error_type=None,
            request_messages=[{"role": m.role, "content": m.content} for m in request.messages],
        )
        started = time.perf_counter()
        try:
            response, structured, activities, final_messages = await self._call_validated(
                request, tools, entry
            )
            entry.request_messages = [
                {"role": m.role, "content": m.content} for m in final_messages
            ]
        except TimeoutError as exc:
            entry.status = AI_STATUS.timeout
            entry.error_type = "TimeoutError"
            raise AITimeoutError("The AI provider did not answer in time") from exc
        except AIValidationError:
            entry.status = AI_STATUS.validation_failed
            entry.validation_ok = False
            entry.error_type = "ValidationError"
            raise
        except AppError:
            raise
        except Exception as exc:
            entry.status = AI_STATUS.provider_error
            entry.error_type = type(exc).__name__
            raise AIProviderError("The AI provider failed") from exc
        else:
            entry.model = response.model
            entry.simulated = response.simulated
            entry.validation_ok = True if response_schema else None
            entry.input_tokens = response.input_tokens
            entry.output_tokens = response.output_tokens
            entry.cost_usd = response.cost_usd
            entry.response_text = response.text
            return GatewayResult(
                text=response.text,
                structured=structured,
                model=response.model,
                provider=response.provider,
                simulated=response.simulated,
                ai_request_id=entry.id,
                tool_activity=activities,
            )
        finally:
            entry.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            await self._log.add(entry)

    async def _call_validated(
        self, request: LLMRequest, tools: Sequence[Tool], entry: AIRequestLogEntry
    ) -> tuple[LLMResponse, BaseModel | None, list[ToolActivity], list[LLMMessage]]:
        registry = {tool.definition.name: tool for tool in tools}
        activities: list[ToolActivity] = []
        messages = list(request.messages)

        # Tool rounds: run requested tools, feed results back, until the
        # model answers or the bound is hit.
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await asyncio.wait_for(
                self._provider.complete(request), timeout=self._timeout
            )
            if not (response.tool_calls and registry):
                break
            for call in response.tool_calls:
                result = await self._run_tool(registry, call.name, call.arguments)
                activities.append(
                    ToolActivity(
                        name=call.name, arguments=call.arguments, result_summary=result.summary
                    )
                )
                entry.tool_calls.append({"name": call.name, "arguments": call.arguments})
                messages.append(LLMMessage("tool", result.content, tool_call_id=call.id))
            request = replace(request, messages=messages)
        else:
            # The bound was exhausted with the model still asking for tools.
            raise AIProviderError("Tool iteration limit reached without an answer")

        attempts = self._validation_retries + 1
        last_error: ValidationError | None = None
        for attempt in range(attempts):
            if attempt > 0:
                response = await asyncio.wait_for(
                    self._provider.complete(request), timeout=self._timeout
                )
            if request.response_schema is None:
                return response, None, activities, messages
            try:
                structured = request.response_schema.model_validate_json(response.text)
                return response, structured, activities, messages
            except ValidationError as exc:
                last_error = exc
        raise AIValidationError(
            f"Output did not match {request.response_schema.__name__} after {attempts} attempts"
        ) from last_error

    async def stream_reply(
        self,
        *,
        prompt_name: str,
        user_messages: list[LLMMessage],
        organization_id: UUID,
        correlation_id: str | None = None,
        tools: Sequence[Tool] = (),
    ):
        """Streaming variant for chat: runs tool rounds, then streams the
        final text. Yields event dicts ({"type": "tool"|"delta"|"result"})
        and audits the call exactly like complete()."""
        prompt = get_prompt(prompt_name)
        request = LLMRequest(
            messages=[LLMMessage("system", prompt.system), *user_messages],
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            tools=[tool.definition for tool in tools],
        )
        entry = AIRequestLogEntry(
            id=str(uuid7()),
            organization_id=str(organization_id),
            provider=self._provider.name,
            model="",
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            status=AI_STATUS.ok,
            simulated=False,
            validation_ok=None,
            latency_ms=0.0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            correlation_id=correlation_id,
            error_type=None,
        )
        registry = {tool.definition.name: tool for tool in tools}
        activities: list[ToolActivity] = []
        messages = list(request.messages)
        started = time.perf_counter()
        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                response = await asyncio.wait_for(
                    self._provider.complete(request), timeout=self._timeout
                )
                if not (response.tool_calls and registry):
                    break
                for call in response.tool_calls:
                    result = await self._run_tool(registry, call.name, call.arguments)
                    activities.append(
                        ToolActivity(
                            name=call.name,
                            arguments=call.arguments,
                            result_summary=result.summary,
                        )
                    )
                    entry.tool_calls.append({"name": call.name, "arguments": call.arguments})
                    messages.append(LLMMessage("tool", result.content, tool_call_id=call.id))
                    yield {"type": "tool", "name": call.name, "summary": result.summary}
                request = replace(request, messages=messages)
            else:
                raise AIProviderError("Tool iteration limit reached without an answer")

            chunks: list[str] = []
            async for delta in self._provider.stream_text(request):
                chunks.append(delta)
                yield {"type": "delta", "text": delta}
            text = "".join(chunks).strip()

            entry.model = getattr(self._provider, "model_name", self._provider.name)
            entry.simulated = bool(getattr(self._provider, "simulated", False))
            entry.input_tokens = sum(len(m.content) for m in messages) // 4
            entry.output_tokens = len(text) // 4
            entry.request_messages = [{"role": m.role, "content": m.content} for m in messages]
            entry.response_text = text
            yield {
                "type": "result",
                "result": GatewayResult(
                    text=text,
                    structured=None,
                    model=entry.model,
                    provider=self._provider.name,
                    simulated=entry.simulated,
                    ai_request_id=entry.id,
                    tool_activity=activities,
                ),
            }
        except TimeoutError as exc:
            entry.status = AI_STATUS.timeout
            entry.error_type = "TimeoutError"
            raise AITimeoutError("The AI provider did not answer in time") from exc
        except AppError:
            entry.status = AI_STATUS.provider_error
            entry.error_type = "AppError"
            raise
        except Exception as exc:
            entry.status = AI_STATUS.provider_error
            entry.error_type = type(exc).__name__
            raise AIProviderError("The AI provider failed") from exc
        finally:
            entry.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            await self._log.add(entry)

    @staticmethod
    async def _run_tool(registry: dict[str, Tool], name: str, arguments: dict) -> ToolResult:
        tool = registry.get(name)
        if tool is None:
            # Defensive: a model naming an unlisted tool gets told so and
            # must answer without it.
            return ToolResult(
                content=f"Tool {name} is not available.",
                summary=f"Blocked a request for the unavailable tool {name}",
            )
        try:
            return await tool.run(arguments)
        except Exception as exc:  # tool failures degrade, never crash the reply
            return ToolResult(
                content=f"The tool {name} failed: {type(exc).__name__}.",
                summary=f"The {name} tool failed",
            )
