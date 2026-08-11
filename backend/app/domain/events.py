"""Domain events. Plain dataclasses, zero framework imports.

Events are PascalCase facts in the past tense. Payloads carry ids, not
clinical text: consumers that need content fetch it from the source of
truth, which keeps message bodies out of broker logs and dead letters.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.ids import uuid7


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Envelope for one fact, written to the outbox in the same transaction
    as the state change it describes."""

    event_type: str
    schema_version: int
    occurred_at: datetime
    organization_id: UUID
    payload: dict
    correlation_id: str | None = None
    causation_id: str | None = None
    event_id: UUID = field(default_factory=uuid7)


PATIENT_MESSAGE_CREATED = "PatientMessageCreated"
AI_RESPONSE_GENERATED = "AIResponseGenerated"
RISK_SIGNAL_DETECTED = "RiskSignalDetected"
RISK_REVIEW_REQUIRED = "RiskReviewRequired"
HUMAN_REVIEW_COMPLETED = "HumanReviewCompleted"


def risk_signal_detected(
    *,
    risk_signal_id: UUID,
    message_id: UUID,
    conversation_id: UUID,
    patient_id: UUID,
    category: str,
    severity: int,
    escalated: bool,
    organization_id: UUID,
    occurred_at: datetime,
    correlation_id: str | None,
    causation_id: str | None,
) -> DomainEvent:
    # Ids and classification only. The evidence quote stays in the database.
    return DomainEvent(
        event_type=RISK_SIGNAL_DETECTED,
        schema_version=1,
        occurred_at=occurred_at,
        organization_id=organization_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload={
            "risk_signal_id": str(risk_signal_id),
            "message_id": str(message_id),
            "conversation_id": str(conversation_id),
            "patient_id": str(patient_id),
            "category": category,
            "severity": severity,
            "escalated": escalated,
        },
    )


def risk_review_required(
    *,
    workflow_id: UUID,
    risk_signal_id: UUID,
    patient_id: UUID,
    severity: int,
    organization_id: UUID,
    occurred_at: datetime,
    correlation_id: str | None,
    causation_id: str | None,
) -> DomainEvent:
    return DomainEvent(
        event_type=RISK_REVIEW_REQUIRED,
        schema_version=1,
        occurred_at=occurred_at,
        organization_id=organization_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload={
            "workflow_id": str(workflow_id),
            "risk_signal_id": str(risk_signal_id),
            "patient_id": str(patient_id),
            "severity": severity,
        },
    )


def human_review_completed(
    *,
    workflow_id: UUID,
    risk_signal_id: UUID,
    reviewer_id: UUID,
    decision: str,
    severity_override: int | None,
    organization_id: UUID,
    occurred_at: datetime,
    correlation_id: str | None,
) -> DomainEvent:
    return DomainEvent(
        event_type=HUMAN_REVIEW_COMPLETED,
        schema_version=1,
        occurred_at=occurred_at,
        organization_id=organization_id,
        correlation_id=correlation_id,
        payload={
            "workflow_id": str(workflow_id),
            "risk_signal_id": str(risk_signal_id),
            "reviewer_id": str(reviewer_id),
            "decision": decision,
            "severity_override": severity_override,
        },
    )


def ai_response_generated(
    *,
    message_id: UUID,
    conversation_id: UUID,
    ai_request_id: UUID,
    simulated: bool,
    organization_id: UUID,
    occurred_at: datetime,
    correlation_id: str | None,
    causation_id: str | None = None,
) -> DomainEvent:
    return DomainEvent(
        event_type=AI_RESPONSE_GENERATED,
        schema_version=1,
        occurred_at=occurred_at,
        organization_id=organization_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload={
            "message_id": str(message_id),
            "conversation_id": str(conversation_id),
            "ai_request_id": str(ai_request_id),
            "simulated": simulated,
        },
    )


def patient_message_created(
    *,
    message_id: UUID,
    conversation_id: UUID,
    patient_id: UUID,
    sender_type: str,
    organization_id: UUID,
    occurred_at: datetime,
    correlation_id: str | None,
) -> DomainEvent:
    return DomainEvent(
        event_type=PATIENT_MESSAGE_CREATED,
        schema_version=1,
        occurred_at=occurred_at,
        organization_id=organization_id,
        correlation_id=correlation_id,
        payload={
            "message_id": str(message_id),
            "conversation_id": str(conversation_id),
            "patient_id": str(patient_id),
            "sender_type": sender_type,
        },
    )
