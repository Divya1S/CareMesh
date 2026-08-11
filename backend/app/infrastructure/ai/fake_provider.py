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
import re
from collections.abc import AsyncIterator

from app.application.ai.types import LLMRequest, LLMResponse, ToolCall

_SOURCE = re.compile(
    r"SOURCE \d+ \[id=([0-9a-f-]+)\] (.+?) v\d+:\n(.*?)(?=\n\nSOURCE|\Z)", re.DOTALL
)

MODEL_NAME = "fake-sim-1"


class FakeProviderError(RuntimeError):
    pass


_SCENARIOS: list[tuple[tuple[str, ...], str]] = [
    (
        ("kill myself", "suicide", "end it", "hurt myself", "hurting myself", "self harm"),
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


def _grounded_answer(user_message: str) -> str:
    """Simulated grounded generation: quotes the top retrieved source and
    cites it. The retrieval feeding this is real; only the wording here is
    canned, and the whole response stays labeled simulated."""
    sources = _SOURCE.findall(user_message)
    if not sources:
        return json.dumps(
            {"answer": "The provided sources do not cover this question.", "cited_chunk_ids": []}
        )
    chunk_id, title, content = sources[0]
    sentences = re.split(r"(?<=[.!?])\s+", content.strip())
    quoted = " ".join(sentences[:2]).strip()
    cited = [chunk_id]
    if len(sources) > 1:
        cited.append(sources[1][0])
    return json.dumps(
        {
            "answer": f"{quoted} (From: {title.strip()}.)",
            "cited_chunk_ids": cited,
        }
    )


def _match_scenario(text: str) -> int:
    lowered = text.lower()
    for index, (keywords, _) in enumerate(_SCENARIOS):
        if any(keyword in lowered for keyword in keywords):
            return index
    return -1


_TOOL_WORDS = {
    "search_resources": (
        "sleep better",
        "grounding",
        "resource",
        "breathing",
        "calm down",
        "tip",
        "advice",
        "technique",
    ),
    "request_appointment": ("appointment", "schedule", "book a", "meet with"),
}


def _pick_tool_call(request: LLMRequest, last_user: str) -> ToolCall | None:
    """Deterministic tool selection: only when tools are offered, no tool
    result is present yet, and the message is not a crisis disclosure
    (crisis always gets the direct crisis reply, never a detour)."""
    if not request.tools or any(m.role == "tool" for m in request.messages):
        return None
    if _match_scenario(last_user) == 0:  # crisis scenario keywords
        return None
    lowered = last_user.lower()
    available = {tool.name for tool in request.tools}
    for name, words in _TOOL_WORDS.items():
        if name in available and any(word in lowered for word in words):
            if name == "search_resources":
                arguments = {"query": last_user[:200]}
            else:
                arguments = {"note": last_user[:200]}
            return ToolCall(id=f"call-{name}", name=name, arguments=arguments)
    return None


def _reply_after_tools(request: LLMRequest) -> str | None:
    """After a tool round, compose the final reply from the tool result."""
    tool_messages = [m for m in request.messages if m.role == "tool"]
    if not tool_messages:
        return None
    last = tool_messages[-1]
    if last.tool_call_id == "call-search_resources":
        try:
            results = json.loads(last.content)
        except json.JSONDecodeError:
            results = []
        if results:
            top = results[0]
            return (
                f"I looked in the resource library for you. {top['snippet']} "
                f"(From: {top['title']}.) Want me to pull up more on this?"
            )
        return (
            "I checked the resource library but did not find anything on "
            "that. Your care team would be a good next step."
        )
    return (
        "I let your care team know you would like an appointment. They will "
        "reach out to set a time. Is there anything you want them to know "
        "beforehand?"
    )


class FakeLLMProvider:
    name = "fake"
    model_name = MODEL_NAME
    simulated = True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        last_user = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        if "[[fail:timeout]]" in last_user:
            await asyncio.sleep(3600)
        if "[[fail:error]]" in last_user:
            raise FakeProviderError("injected provider failure")

        tool_call = _pick_tool_call(request, last_user)
        if tool_call is not None:
            await asyncio.sleep(0.01)
            return LLMResponse(
                text="",
                model=MODEL_NAME,
                provider=self.name,
                input_tokens=sum(len(m.content) for m in request.messages) // 4,
                output_tokens=8,
                cost_usd=0.0,
                simulated=True,
                tool_calls=[tool_call],
            )

        after_tools = _reply_after_tools(request)
        if after_tools is not None and request.response_schema is None:
            await asyncio.sleep(0.01)
            return LLMResponse(
                text=after_tools,
                model=MODEL_NAME,
                provider=self.name,
                input_tokens=sum(len(m.content) for m in request.messages) // 4,
                output_tokens=len(after_tools) // 4,
                cost_usd=0.0,
                simulated=True,
            )

        scenario = _match_scenario(last_user)
        if request.response_schema is not None:
            if "[[fail:malformed]]" in last_user:
                text = '{"category": "not-a-category", "severity": 99}'
            elif request.prompt_name == "knowledge_answer":
                text = _grounded_answer(last_user)
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

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        """Streams the same deterministic reply in word chunks. A real
        adapter yields real tokens through this same interface."""
        response = await self.complete(request)
        words = response.text.split(" ")
        for index in range(0, len(words), 3):
            yield " ".join(words[index : index + 3]) + " "
            await asyncio.sleep(0.02)
