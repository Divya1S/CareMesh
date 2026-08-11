"""Risk domain: structured signals, deterministic escalation, review decisions.

The AI produces signals; this module decides what happens with them. That
split is deliberate: escalation is deterministic code with unit tests, never
a model's judgment call (build spec, product principle 3).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class RiskCategory(StrEnum):
    NONE = "none"
    LOW_MOOD = "low_mood"
    ANXIETY = "anxiety"
    SELF_HARM = "self_harm"
    CRISIS = "crisis"


class ReviewDecision(StrEnum):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class RiskSignal:
    """An AI detected signal. Never a diagnosis; always reviewed by a human
    before it changes anyone's care."""

    id: UUID
    organization_id: UUID
    conversation_id: UUID
    message_id: UUID
    patient_id: UUID
    category: RiskCategory
    severity: int
    confidence: float
    evidence: str
    model: str
    prompt_version: int
    ai_request_id: UUID
    simulated: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RiskReview:
    """The human decision record for one signal."""

    id: UUID
    organization_id: UUID
    risk_signal_id: UUID
    reviewer_id: UUID
    decision: ReviewDecision
    severity_override: int | None
    note: str
    created_at: datetime


# Deterministic escalation policy. Reviewed and tested, not prompted.
ESCALATION_SEVERITY_THRESHOLD = 2
ALWAYS_ESCALATE_CATEGORIES = frozenset({RiskCategory.SELF_HARM, RiskCategory.CRISIS})

# Deterministic crisis language floor. A model (real or steered by a
# crafted message) can under classify; text that hits these phrases
# escalates to human review and makes Dira's tools unavailable for the
# turn regardless of what any model says. Deliberately high precision:
# the model still catches the paraphrases this list misses.
CRISIS_PHRASES = (
    "kill myself",
    "suicide",
    "suicidal",
    "end my life",
    "end it all",
    "hurt myself",
    "hurting myself",
    "harm myself",
    "self harm",
    "self-harm",
    "want to die",
    "better off dead",
)


def contains_crisis_language(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in CRISIS_PHRASES)


def escalation_required(category: RiskCategory, severity: int) -> bool:
    if category in ALWAYS_ESCALATE_CATEGORIES:
        return True
    return severity >= ESCALATION_SEVERITY_THRESHOLD
