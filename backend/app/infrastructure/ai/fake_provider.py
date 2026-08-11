# SIMULATED
"""The fake LLM provider (ADR 0002). This is the dev and test default.

It is a simulation and is always labeled as one: every response carries
simulated=True, which flows through the gateway log, the API, and the UI as
a visible SIMULATED badge. Replacement path: set LLM_PROVIDER to a real
adapter name and provide LLM_API_KEY; the interface is identical.

Behavior is deterministic and scenario driven so tests, evals, and demos
are reproducible and free. Failure modes are injectable through markers in
the last user message:
  [[fail:timeout]]    sleeps past any reasonable gateway timeout
  [[fail:malformed]]  returns JSON that does not match the schema
  [[fail:error]]      raises a provider error
"""

import asyncio
import json

from app.application.ai.types import LLMRequest, LLMResponse

MODEL_NAME = "fake-sim-1"


class FakeProviderError(RuntimeError):
    pass


_SCENARIOS: list[tuple[tuple[str, ...], str]] = [
    (
        ("kill myself", "suicide", "end it", "hurt myself", "self harm"),
        "I'm really glad you told me, and I want you to know this matters. "
        "I'm an AI companion and not able to keep you safe on my own, so "
        "please use the crisis resources at the top of this page right now, "
        "and your care team has been made aware. You deserve support from a "
        "real person, today.",
    ),
    (
        ("sad", "down", "depressed", "cry", "lonely", "hopeless"),
        "That sounds heavy, and carrying it alone makes it heavier. Thank "
        "you for putting it into words. Would it help to tell me when this "
        "feeling is strongest? Your therapist can see this conversation, "
        "and I can help you get an appointment if you want one.",
    ),
    (
        ("exam", "test", "school", "grades", "homework", "sleep"),
        "Exams have a way of taking over everything, including nights. One "
        "small step that often helps: write down the one thing that worries "
        "you most about it, and we can look at it together. If sleep keeps "
        "being hard, that is worth telling your care team too.",
    ),
    (
        ("appointment", "schedule", "meet", "therapist"),
        "I can help with that. Appointment booking opens in a later part of "
        "this app, and your care team can see that you asked. Is there "
        "anything you would like them to know before you meet?",
    ),
]

_DEFAULT_REPLY = (
    "Thank you for sharing that with me. I'm here to listen, and your care "
    "team can see this space too. Would you like to tell me a bit more "
    "about what today has been like?"
)

_RISK_BY_SCENARIO = [
    ("crisis", 3, 0.9),
    ("low_mood", 1, 0.7),
    ("anxiety", 1, 0.6),
    ("none", 0, 0.8),
]


def _match_scenario(text: str) -> int:
    lowered = text.lower()
    for index, (keywords, _) in enumerate(_SCENARIOS):
        if any(keyword in lowered for keyword in keywords):
            return index
    return -1


class FakeLLMProvider:
    name = "fake"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        last_user = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        if "[[fail:timeout]]" in last_user:
            await asyncio.sleep(3600)
        if "[[fail:error]]" in last_user:
            raise FakeProviderError("injected provider failure")

        scenario = _match_scenario(last_user)
        if request.response_schema is not None:
            if "[[fail:malformed]]" in last_user:
                text = '{"category": "not-a-category", "severity": 99}'
            else:
                category, severity, confidence = _RISK_BY_SCENARIO[
                    scenario if 0 <= scenario < len(_RISK_BY_SCENARIO) else 3
                ]
                text = json.dumps(
                    {
                        "category": category,
                        "severity": severity,
                        "confidence": confidence,
                        "evidence": last_user[:120],
                    }
                )
        else:
            text = _SCENARIOS[scenario][1] if scenario >= 0 else _DEFAULT_REPLY

        # Simulated latency keeps the UI honest without slowing tests.
        await asyncio.sleep(0.01)
        return LLMResponse(
            text=text,
            model=MODEL_NAME,
            provider=self.name,
            input_tokens=sum(len(m.content) for m in request.messages) // 4,
            output_tokens=len(text) // 4,
            cost_usd=0.0,
            simulated=True,
        )
