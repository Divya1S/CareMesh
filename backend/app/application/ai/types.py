"""Types shared between the AI Gateway and providers."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: list[LLMMessage]
    prompt_name: str
    prompt_version: int
    # When set, the provider must answer with JSON matching this schema.
    response_schema: type[BaseModel] | None = None
    max_output_tokens: int = 1024


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    simulated: bool


@dataclass(frozen=True, slots=True)
class GatewayResult:
    """What business logic receives. The simulated flag must survive all the
    way to the UI; it is never dropped."""

    text: str
    structured: BaseModel | None
    model: str
    provider: str
    simulated: bool
    ai_request_id: str


@dataclass(frozen=True, slots=True)
class AIErrors:
    provider_error: str = "provider_error"
    validation_failed: str = "validation_failed"
    timeout: str = "timeout"
    ok: str = "ok"


AI_STATUS = AIErrors()


@dataclass(slots=True)
class AIRequestLogEntry:
    """One gateway call, success or failure. Written for every call."""

    id: str
    organization_id: str
    provider: str
    model: str
    prompt_name: str
    prompt_version: int
    status: str
    simulated: bool
    validation_ok: bool | None
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    correlation_id: str | None
    error_type: str | None
    request_messages: list[dict] = field(default_factory=list)
    response_text: str | None = None
