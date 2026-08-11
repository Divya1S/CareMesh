"""Provider selection by env var (ADR 0002). The fake provider is the
default; the Gemini adapter is opt in via LLM_PROVIDER=gemini plus a key.
Unimplemented names fail loudly instead of pretending. An Ollama adapter
for local models is the documented path for a second free provider;
Anthropic and OpenAI adapters would follow the same shape but have no
free tier, so they stay out by the zero cost rule."""

from collections.abc import Callable

from app.application.ai.gateway import LLMProvider
from app.infrastructure.ai.fake_provider import FakeLLMProvider

_REGISTRY: dict[str, Callable[[], LLMProvider]] = {
    "fake": FakeLLMProvider,
}

_PLANNED = ("anthropic", "openai", "ollama")


def register_provider(name: str, factory: Callable[[], LLMProvider]) -> None:
    _REGISTRY[name] = factory


def create_provider(name: str) -> LLMProvider:
    if name == "gemini":
        from app.infrastructure.ai.gemini_provider import DEFAULT_MODEL, GeminiProvider
        from app.infrastructure.settings import get_settings

        settings = get_settings()
        return GeminiProvider(
            api_key=settings.llm_api_key or "",
            model=settings.llm_model or DEFAULT_MODEL,
        )
    if name in _REGISTRY:
        return _REGISTRY[name]()
    if name in _PLANNED:
        raise RuntimeError(
            f"LLM_PROVIDER={name} is recognized but not implemented. The "
            "fake provider is the free default and gemini is the free tier "
            "real adapter; other providers have no free tier."
        )
    raise RuntimeError(f"Unknown LLM_PROVIDER: {name}")
