"""Provider selection by env var (ADR 0002). The fake provider is the
default; real adapters are opt in and cost money, so selecting one without
implementing and configuring it fails loudly instead of pretending."""

from collections.abc import Callable

from app.application.ai.gateway import LLMProvider
from app.infrastructure.ai.fake_provider import FakeLLMProvider

_REGISTRY: dict[str, Callable[[], LLMProvider]] = {
    "fake": FakeLLMProvider,
}

_PLANNED = ("anthropic", "openai", "gemini")


def register_provider(name: str, factory: Callable[[], LLMProvider]) -> None:
    _REGISTRY[name] = factory


def create_provider(name: str) -> LLMProvider:
    if name in _REGISTRY:
        return _REGISTRY[name]()
    if name in _PLANNED:
        raise RuntimeError(
            f"LLM_PROVIDER={name} is recognized but its adapter is not "
            "implemented yet. Real adapters land when real API usage is "
            "switched on (they cost money); dev runs on LLM_PROVIDER=fake."
        )
    raise RuntimeError(f"Unknown LLM_PROVIDER: {name}")
