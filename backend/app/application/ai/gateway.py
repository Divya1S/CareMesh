"""The AI Gateway: the only path from business logic to any LLM.

Responsibilities here: prompt resolution, timeout, the bounded tool loop,
structured output validation with one bounded retry, and logging every
call, success or failure, to the AI request log. Provider selection
happens in infrastructure; business logic only ever sees this class.
"""

import asyncio
import time
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from dataclasses import replace
from typing import Protocol
from uuid import UUID

import structlog
from pydantic import BaseModel, ValidationError

from app.application.ai.prompts import Prompt, get_prompt
from app.application.ai.tools import Tool, ToolResult, validate_arguments
from app.application.ai.types import (
    AI_STATUS,
    AIRequestLogEntry,
    GatewayResult,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    StreamDelta,
    ToolActivity,
    ToolCall,
)
from app.application.errors import AppError
from app.domain.ids import uuid7

logger = structlog.get_logger()

# Audit writes handed off when the request task is being cancelled (client
# disconnect). Kept referenced so the event loop never drops them half done.
_detached_log_writes: set[asyncio.Task] = set()

# A model gets at most this many rounds of tool use before it must answer,
# and at most this many executed tool calls per round. Both bounds are
# cost and blast radius controls: a steered model cannot fan one message
# out into an unbounded pile of tool side effects.
MAX_TOOL_ITERATIONS = 3
MAX_TOOL_CALLS_PER_ROUND = 1


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
    model_name: str
    simulated: bool

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    def stream(self, request: LLMRequest) -> AsyncGenerator[StreamDelta | LLMResponse]:
        """Yields text deltas, then exactly one LLMResponse."""
        ...


class AIRequestLog(Protocol):
    async def add(self, entry: AIRequestLogEntry) -> None: ...


def _transcript(messages: Sequence[LLMMessage]) -> list[dict]:
    """The audit copy of a conversation, including tool calls and results."""
    out: list[dict] = []
    for m in messages:
        item: dict = {"role": m.role, "content": m.content}
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            item["tool_calls"] = [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls
            ]
        out.append(item)
    return out


def _short_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "output: invalid"
    first = errors[0]
    location = ".".join(str(part) for part in first["loc"]) or "output"
    return f"{location}: {first['msg']}"[:200]


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

    def _new_entry(
        self, prompt: Prompt, organization_id: UUID, correlation_id: str | None, request: LLMRequest
    ) -> AIRequestLogEntry:
        # Provenance defaults to simulated: wrongly labeling real output as
        # SIMULATED is safe, the reverse is not.
        return AIRequestLogEntry(
            id=str(uuid7()),
            organization_id=str(organization_id),
            provider=self._provider.name,
            model="",
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            status=AI_STATUS.ok,
            simulated=bool(getattr(self._provider, "simulated", True)),
            validation_ok=None,
            latency_ms=0.0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            correlation_id=correlation_id,
            error_type=None,
            request_messages=_transcript(request.messages),
        )

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
        entry = self._new_entry(prompt, organization_id, correlation_id, request)
        started = time.perf_counter()
        try:
            response, structured, activities, final_messages = await self._call_validated(
                request, tools, entry
            )
            entry.request_messages = _transcript(final_messages)
        except TimeoutError as exc:
            entry.status = AI_STATUS.timeout
            entry.error_type = "TimeoutError"
            raise AITimeoutError("The AI provider did not answer in time") from exc
        except AIValidationError:
            entry.status = AI_STATUS.validation_failed
            entry.validation_ok = False
            entry.error_type = "ValidationError"
            raise
        except AppError as exc:
            # Typed failures from inside the loop (a failed mutating tool,
            # the round bound) are provider errors in the audit trail too.
            entry.status = AI_STATUS.provider_error
            entry.error_type = type(exc).__name__
            raise
        except Exception as exc:
            entry.status = AI_STATUS.provider_error
            entry.error_type = type(exc).__name__
            raise AIProviderError("The AI provider failed") from exc
        else:
            entry.model = response.model
            entry.simulated = response.simulated
            entry.validation_ok = True if response_schema else None
            # Usage was accumulated per provider call, so a tool
            # conversation is billed as the sum of its rounds.
            entry.response_text = response.text
            return GatewayResult(
                text=response.text,
                structured=structured,
                model=response.model,
                provider=response.provider,
                simulated=response.simulated,
                ai_request_id=entry.id,
                prompt_version=prompt.version,
                tool_activity=activities,
            )
        finally:
            entry.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            await self._log_safely(entry)

    @staticmethod
    def _accumulate_usage(entry: AIRequestLogEntry, response: LLMResponse) -> None:
        entry.input_tokens += response.input_tokens
        entry.output_tokens += response.output_tokens
        entry.cost_usd += response.cost_usd

    def _log_detached(self, entry: AIRequestLogEntry) -> None:
        """For the cancellation path. Starlette cancels a disconnected
        response through an anyio cancel scope, which cancels every later
        await in the same task, including an audit write in a finally
        block. A fresh task sits outside that scope and completes."""
        task = asyncio.ensure_future(self._log_safely(entry))
        _detached_log_writes.add(task)
        task.add_done_callback(_detached_log_writes.discard)

    @staticmethod
    async def flush_detached_log_writes() -> None:
        """Waits for audit writes handed off on the cancellation path. The
        app calls it at shutdown so no audit row is lost to process exit."""
        if _detached_log_writes:
            await asyncio.gather(*list(_detached_log_writes), return_exceptions=True)

    async def _log_safely(self, entry: AIRequestLogEntry) -> None:
        """Auditing must never become a failure mode of the thing it audits:
        an exception raised here (inside the callers' finally blocks) would
        replace the real error and roll back the patient's message."""
        try:
            await self._log.add(entry)
        except Exception as exc:
            logger.error(
                "ai_request_log_write_failed",
                ai_request_id=entry.id,
                prompt_name=entry.prompt_name,
                error_type=type(exc).__name__,
            )

    async def _tool_rounds(
        self, request: LLMRequest, tools: Sequence[Tool], entry: AIRequestLogEntry, *, stream: bool
    ) -> AsyncIterator[dict]:
        """The bounded tool loop, shared by complete() and stream_reply().

        Yields {"type": "tool"} after each executed call, {"type": "delta"}
        for streamed text, and finally one {"type": "final"} carrying the
        last response, the full message list, the activities, and every
        round's text. Each round is one provider call, bounded by the
        timeout; streamed rounds stream from the first call, so the answer
        is never generated twice.
        """
        registry = {tool.definition.name: tool for tool in tools}
        activities: list[ToolActivity] = []
        messages = list(request.messages)
        texts: list[str] = []
        for _ in range(MAX_TOOL_ITERATIONS):
            if stream:
                response: LLMResponse | None = None
                async for item in self._stream_round(request):
                    if isinstance(item, StreamDelta):
                        if item.text:
                            yield {"type": "delta", "text": item.text}
                    else:
                        response = item
                if response is None:
                    raise AIProviderError("The AI provider stream ended without a response")
            else:
                response = await asyncio.wait_for(
                    self._provider.complete(request), timeout=self._timeout
                )
            self._accumulate_usage(entry, response)
            if response.finish_reason == "MAX_TOKENS":
                logger.warning(
                    "ai_response_truncated", prompt_name=request.prompt_name, ai_request_id=entry.id
                )
            if response.text:
                texts.append(response.text)
            if not (response.tool_calls and registry):
                yield {
                    "type": "final",
                    "response": response,
                    "messages": messages,
                    "activities": activities,
                    "texts": texts,
                }
                return

            # A faithful transcript: the model's own call turn, then results.
            messages.append(
                LLMMessage("assistant", response.text, tool_calls=list(response.tool_calls))
            )
            for index, call in enumerate(response.tool_calls):
                if index >= MAX_TOOL_CALLS_PER_ROUND:
                    # Over budget. Tell the model rather than drop the call
                    # silently, so it can ask again next round if it must.
                    messages.append(
                        LLMMessage(
                            "tool",
                            f"Skipped: at most {MAX_TOOL_CALLS_PER_ROUND} tool call runs per "
                            "round. Ask again if you still need it.",
                            tool_call_id=call.id,
                        )
                    )
                    entry.tool_calls.append(
                        {"name": call.name, "arguments": call.arguments, "skipped": True}
                    )
                    continue
                result = await self._run_tool(registry, call)
                activities.append(
                    ToolActivity(
                        name=call.name, arguments=call.arguments, result_summary=result.summary
                    )
                )
                entry.tool_calls.append({"name": call.name, "arguments": call.arguments})
                messages.append(LLMMessage("tool", result.content, tool_call_id=call.id))
                yield {"type": "tool", "name": call.name, "summary": result.summary}
            request = replace(request, messages=messages)
        # The bound was exhausted with the model still asking for tools.
        raise AIProviderError("Tool iteration limit reached without an answer")

    async def _stream_round(self, request: LLMRequest) -> AsyncIterator[StreamDelta | LLMResponse]:
        """One provider stream under a whole round deadline. Each item is
        awaited with the time left, so no timeout context ever spans a
        yield: a timeout that expired while the consumer was busy would
        otherwise cancel the consumer's own await instead of the provider."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        stream = self._provider.stream(request)
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError("stream round deadline passed")
                try:
                    item = await asyncio.wait_for(anext(stream), timeout=remaining)
                except StopAsyncIteration:
                    return
                yield item
        finally:
            await stream.aclose()

    async def _call_validated(
        self, request: LLMRequest, tools: Sequence[Tool], entry: AIRequestLogEntry
    ) -> tuple[LLMResponse, BaseModel | None, list[ToolActivity], list[LLMMessage]]:
        final: dict | None = None
        async for event in self._tool_rounds(request, tools, entry, stream=False):
            if event["type"] == "final":
                final = event
        assert final is not None  # _tool_rounds either yields final or raises
        response: LLMResponse = final["response"]
        messages: list[LLMMessage] = final["messages"]
        activities: list[ToolActivity] = final["activities"]

        schema = request.response_schema
        if schema is None:
            return response, None, activities, messages

        attempts = self._validation_retries + 1
        last_error: ValidationError | None = None
        for attempt in range(attempts):
            if attempt > 0 and last_error is not None:
                # Feed the failure back so the model can correct itself; a
                # blind resample only hopes for luck.
                retry_messages = [
                    *messages,
                    LLMMessage("assistant", response.text),
                    LLMMessage(
                        "user",
                        "Your previous reply did not match the required JSON schema "
                        f"({_short_validation_error(last_error)}). Reply again with only "
                        "the JSON object.",
                    ),
                ]
                response = await asyncio.wait_for(
                    self._provider.complete(replace(request, messages=retry_messages)),
                    timeout=self._timeout,
                )
                self._accumulate_usage(entry, response)
            try:
                structured = schema.model_validate_json(response.text)
                return response, structured, activities, messages
            except ValidationError as exc:
                last_error = exc
        raise AIValidationError(
            f"Output did not match {schema.__name__} after {attempts} attempts"
        ) from last_error

    async def stream_reply(
        self,
        *,
        prompt_name: str,
        user_messages: list[LLMMessage],
        organization_id: UUID,
        correlation_id: str | None = None,
        tools: Sequence[Tool] = (),
    ) -> AsyncIterator[dict]:
        """Streaming variant for chat: tool rounds and the final text all
        stream from the provider. Yields event dicts ({"type": "start" |
        "tool" | "delta" | "result"}) and audits the call exactly like
        complete()."""
        prompt = get_prompt(prompt_name)
        request = LLMRequest(
            messages=[LLMMessage("system", prompt.system), *user_messages],
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            tools=[tool.definition for tool in tools],
        )
        entry = self._new_entry(prompt, organization_id, correlation_id, request)
        started = time.perf_counter()
        logged = False
        try:
            # Provenance goes out before any text so the UI labels the live
            # bubble from data.
            yield {"type": "start", "simulated": entry.simulated}
            final: dict | None = None
            async for event in self._tool_rounds(request, tools, entry, stream=True):
                if event["type"] == "final":
                    final = event
                else:
                    yield event
            assert final is not None
            response: LLMResponse = final["response"]
            # Text from every round, in order. A tool round normally has
            # none; when a model talks before calling a tool, that text was
            # already streamed and belongs in the reply.
            text = "\n\n".join(t.strip() for t in final["texts"] if t.strip()).strip()
            if not text:
                # A safety blocked or dried up stream must surface as a
                # failure, not persist an empty reply audited as ok. The
                # worst case is exactly a crisis message tripping a real
                # provider's filter and the student seeing a blank bubble.
                raise AIProviderError("The AI provider streamed no text")
            entry.model = response.model
            entry.simulated = response.simulated
            entry.request_messages = _transcript(final["messages"])
            entry.response_text = text
            yield {
                "type": "result",
                "result": GatewayResult(
                    text=text,
                    structured=None,
                    model=response.model,
                    provider=self._provider.name,
                    simulated=response.simulated,
                    ai_request_id=entry.id,
                    prompt_version=prompt.version,
                    tool_activity=final["activities"],
                ),
            }
        except TimeoutError as exc:
            entry.status = AI_STATUS.timeout
            entry.error_type = "TimeoutError"
            raise AITimeoutError("The AI provider did not answer in time") from exc
        except (asyncio.CancelledError, GeneratorExit):
            # The client went away mid stream. The reply was never persisted,
            # so the audit row must not claim the call succeeded. This task
            # is being cancelled, so the write cannot be awaited here.
            entry.status = AI_STATUS.cancelled
            entry.error_type = "ClientDisconnected"
            entry.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            self._log_detached(entry)
            logged = True
            raise
        except AppError as exc:
            entry.status = AI_STATUS.provider_error
            entry.error_type = type(exc).__name__
            raise
        except Exception as exc:
            entry.status = AI_STATUS.provider_error
            entry.error_type = type(exc).__name__
            raise AIProviderError("The AI provider failed") from exc
        finally:
            if not logged:
                entry.latency_ms = round((time.perf_counter() - started) * 1000, 1)
                await self._log_safely(entry)

    @staticmethod
    async def _run_tool(registry: dict[str, Tool], call: ToolCall) -> ToolResult:
        tool = registry.get(call.name)
        if tool is None:
            # Defensive: a model naming an unlisted tool gets told so and
            # must answer without it.
            return ToolResult(
                content=f"Tool {call.name} is not available.",
                summary=f"Blocked a request for the unavailable tool {call.name}",
            )
        problem = validate_arguments(tool.definition.parameters, call.arguments)
        if problem is not None:
            # Model output is untrusted input; the handler never sees it.
            logger.warning("tool_arguments_rejected", tool=call.name, problem=problem)
            return ToolResult(
                content=f"Invalid arguments for {call.name}: {problem}.",
                summary=f"Rejected invalid arguments for {call.name}",
            )
        try:
            return await tool.run(call.arguments)
        except Exception as exc:
            logger.warning("tool_failed", tool=call.name, error_type=type(exc).__name__)
            if tool.mutates:
                # A failed write has likely poisoned the session; degrading
                # would keep streaming over a transaction that can no longer
                # commit and could tell the user a write happened when it
                # did not. Abort the reply instead.
                raise AIProviderError(f"The {call.name} tool failed mid write") from exc
            # Read only tool failures degrade: the model answers without it.
            return ToolResult(
                content=f"The tool {call.name} failed: {type(exc).__name__}.",
                summary=f"The {call.name} tool failed",
            )
