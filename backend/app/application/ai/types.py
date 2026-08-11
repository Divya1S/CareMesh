"""Types shared between the AI Gateway and providers."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    # Set on role="tool" messages: which call this result answers.
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolDef:
    """What the model is told about a tool. Handlers live elsewhere; the
    provider only ever sees this declaration."""

    name: str
    description: str
    parameters: dict  # JSON schema for the arguments


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: list[LLMMessage]
    prompt_name: str
    prompt_version: int
    # When set, the provider must answer with JSON matching this schema.
    response_schema: type[BaseModel] | None = None
    tools: list[ToolDef] = field(default_factory=list)
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
    # Nonempty when the model wants tools run before answering.
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ToolActivity:
    """One executed tool call, surfaced to the caller and the UI."""

    name: str
    arguments: dict
    result_summary: str


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
    tool_activity: list[ToolActivity] = field(default_factory=list)


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
    tool_calls: list[dict] = field(default_factory=list)
