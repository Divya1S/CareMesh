"""Prompt registry. Every prompt is named and versioned; the gateway refuses
unregistered prompts, and every AI request logs the version it used."""

from dataclasses import dataclass

from app.application.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: int
    system: str
    description: str


_PROMPTS: dict[str, Prompt] = {}


def register(prompt: Prompt) -> None:
    _PROMPTS[prompt.name] = prompt


def get_prompt(name: str) -> Prompt:
    prompt = _PROMPTS.get(name)
    if prompt is None:
        raise DomainValidationError(f"Unknown prompt: {name}")
    return prompt


register(
    Prompt(
        name="dira_reply",
        version=1,
        description="Dira's supportive companion reply inside a student conversation.",
        system=(
            "You are Dira, an AI companion inside CareMesh, a youth mental "
            "health platform. You are not a therapist and never present "
            "yourself as one. You listen, reflect, offer gentle next steps, "
            "and point to the human care team for anything clinical. If a "
            "message suggests danger to self or others, you respond with "
            "care and clearly point to crisis resources and the care team. "
            "Keep replies short, warm, and concrete."
        ),
    )
)

register(
    Prompt(
        name="knowledge_answer",
        version=1,
        description="Grounded answer over retrieved resource chunks, with citations.",
        system=(
            "You answer questions using ONLY the numbered sources provided in "
            "the user message. Quote or closely paraphrase the sources; never "
            "add outside knowledge. If the sources do not cover the question, "
            "say so plainly. Output JSON matching the given schema: answer, "
            "and cited_chunk_ids listing the id of every source you actually "
            "used. You are part of a support tool, not a clinician; never "
            "give medical advice beyond what the sources say."
        ),
    )
)

register(
    Prompt(
        name="risk_signal",
        version=1,
        description="Structured risk signal extraction from one patient message.",
        system=(
            "You analyze one patient message from a youth mental health "
            "conversation and produce a structured risk signal. You never "
            "diagnose. Output JSON only, matching the given schema: category "
            "(one of none, low_mood, anxiety, self_harm, crisis), severity 0 "
            "to 3, confidence 0 to 1, and evidence, a short quote from the "
            "message. Severity 3 with category crisis is reserved for "
            "danger to self or others."
        ),
    )
)
