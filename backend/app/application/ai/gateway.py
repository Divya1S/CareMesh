"""The AI Gateway: the only path from business logic to any LLM.

Responsibilities here: prompt resolution, timeout, structured output
validation with one bounded retry, and logging every call, success or
failure, to the AI request log. Provider selection happens in
infrastructure; business logic only ever sees this class.
"""

import asyncio
import time
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.application.ai.prompts import get_prompt
from app.application.ai.types import (
    AI_STATUS,
    AIRequestLogEntry,
    GatewayResult,
    LLMMessage,
    LLMRequest,
    LLMResponse,
)
from app.application.errors import AppError
from app.domain.ids import uuid7


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
    ) -> GatewayResult:
        prompt = get_prompt(prompt_name)
        request = LLMRequest(
            messages=[LLMMessage("system", prompt.system), *user_messages],
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            response_schema=response_schema,
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
            response, structured = await self._call_validated(request)
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
            )
        finally:
            entry.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            await self._log.add(entry)

    async def _call_validated(self, request: LLMRequest) -> tuple[LLMResponse, BaseModel | None]:
        attempts = self._validation_retries + 1
        last_error: ValidationError | None = None
        for _ in range(attempts):
            response = await asyncio.wait_for(
                self._provider.complete(request), timeout=self._timeout
            )
            if request.response_schema is None:
                return response, None
            try:
                return response, request.response_schema.model_validate_json(response.text)
            except ValidationError as exc:
                last_error = exc
        raise AIValidationError(
            f"Output did not match {request.response_schema.__name__} after {attempts} attempts"
        ) from last_error
