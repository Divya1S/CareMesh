"""Opt in live check: prove a real model flows through the AI Gateway.

Never part of verify.sh or CI. It spends real API quota (free tier), so
you run it on purpose:

    cd backend && uv run python -m scripts.live_check

Requires LLM_API_KEY in backend/.env (a Gemini key). It runs three
checks through the same AIGateway the app uses and prints the audit
entries, which must show simulated=false:

1. A dira_reply completion (plain text).
2. A risk_signal completion validated against the RiskDraft schema.
3. A streamed dira_reply, counting chunks.
"""

import asyncio
import sys
from uuid import uuid4

from app.application.ai.gateway import AIGateway
from app.application.ai.types import AIRequestLogEntry, LLMMessage
from app.application.use_cases.risk_analysis import RiskDraft
from app.infrastructure.ai.gemini_provider import DEFAULT_MODEL, GeminiProvider
from app.infrastructure.settings import get_settings


class PrintLog:
    def __init__(self) -> None:
        self.entries: list[AIRequestLogEntry] = []

    async def add(self, entry: AIRequestLogEntry) -> None:
        self.entries.append(entry)
        print(
            f"  audit: prompt={entry.prompt_name} v{entry.prompt_version} "
            f"provider={entry.provider} model={entry.model} "
            f"status={entry.status} simulated={entry.simulated} "
            f"tokens={entry.input_tokens}/{entry.output_tokens} "
            f"latency={entry.latency_ms:.0f}ms cost=${entry.cost_usd:.4f}"
        )


async def main() -> int:
    settings = get_settings()
    if not settings.llm_api_key:
        print("LLM_API_KEY is not set in backend/.env, nothing to check.")
        return 1

    provider = GeminiProvider(
        api_key=settings.llm_api_key, model=settings.llm_model or DEFAULT_MODEL
    )
    log = PrintLog()
    gateway = AIGateway(provider, log, timeout_seconds=settings.ai_timeout_seconds)
    org = uuid4()
    failures = 0

    print(f"Live check against {provider.name}:{provider.model_name}\n")

    print("1. dira_reply completion")
    try:
        result = await gateway.complete(
            prompt_name="dira_reply",
            user_messages=[
                LLMMessage("user", "Exams are coming and I cannot sleep. Any small tips?")
            ],
            organization_id=org,
        )
        print(f"  simulated={result.simulated}")
        print(f"  reply: {result.text[:200]}")
        if result.simulated:
            failures += 1
    except Exception as exc:
        print(f"  FAILED: {exc}")
        failures += 1

    print("\n2. risk_signal structured completion")
    try:
        result = await gateway.complete(
            prompt_name="risk_signal",
            user_messages=[LLMMessage("user", "I feel really stressed and alone since the move.")],
            organization_id=org,
            response_schema=RiskDraft,
        )
        draft: RiskDraft = result.structured
        print(
            f"  simulated={result.simulated} category={draft.category} "
            f"severity={draft.severity} confidence={draft.confidence}"
        )
        if result.simulated:
            failures += 1
    except Exception as exc:
        print(f"  FAILED: {exc}")
        failures += 1

    print("\n3. streamed dira_reply")
    try:
        chunks = 0
        final_text = ""
        async for event in gateway.stream_reply(
            prompt_name="dira_reply",
            user_messages=[LLMMessage("user", "Just checking in, I had an okay day.")],
            organization_id=org,
        ):
            if event.get("type") == "delta":
                chunks += 1
            if event.get("type") == "result":
                final_text = event["result"].text
        print(f"  chunks={chunks} final_length={len(final_text)}")
        if chunks == 0:
            failures += 1
    except Exception as exc:
        print(f"  FAILED: {exc}")
        failures += 1

    print(f"\n{'PASS' if failures == 0 else 'FAIL'}: {3 - failures}/3 checks passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
