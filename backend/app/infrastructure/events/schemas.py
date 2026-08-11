"""Wire schema for event envelopes on the broker. Pydantic at the boundary."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.events import DomainEvent


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: str
    schema_version: int
    occurred_at: datetime
    organization_id: UUID
    correlation_id: str | None = None
    causation_id: str | None = None
    payload: dict

    @classmethod
    def from_domain(cls, event: DomainEvent) -> "EventEnvelope":
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            schema_version=event.schema_version,
            occurred_at=event.occurred_at,
            organization_id=event.organization_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            payload=event.payload,
        )


def topic_for(prefix: str, event_type: str) -> str:
    """caremesh.<domain>.<event>: PatientMessageCreated becomes
    caremesh.conversation.patient_message_created."""
    domain = _DOMAIN_BY_EVENT.get(event_type, "system")
    snake = "".join(
        f"_{ch.lower()}" if ch.isupper() and i > 0 else ch.lower()
        for i, ch in enumerate(event_type)
    )
    return f"{prefix}.{domain}.{snake}"


def dlq_topic_for(topic: str) -> str:
    return f"{topic}.dlq"


_DOMAIN_BY_EVENT = {
    "PatientMessageCreated": "conversation",
    "AIResponseGenerated": "ai",
    "RiskSignalDetected": "risk",
    "RiskReviewRequired": "risk",
    "HumanReviewCompleted": "risk",
    "ReferralSubmitted": "referral",
    "ReferralDecided": "referral",
    "GuardianNotificationRequired": "guardian",
}
