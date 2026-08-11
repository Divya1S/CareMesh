"""Risk analysis: AI produces a structured signal, deterministic code
decides whether a human review workflow starts. Runs inside the event
consumer, in the same transaction as the idempotency mark."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.application.ai.gateway import AIGateway
from app.application.ai.types import LLMMessage
from app.application.errors import NotFoundError
from app.domain import events as domain_events
from app.domain.ids import uuid7
from app.domain.risk import (
    RiskCategory,
    RiskSignal,
    contains_crisis_language,
    escalation_required,
)
from app.domain.workflows import RiskEscalationState, WorkflowType


class RiskDraft(BaseModel):
    """What the risk_signal prompt must return. Validated by the gateway."""

    category: RiskCategory
    severity: int = Field(ge=0, le=3)
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(max_length=500)


class RiskAnalysisService:
    def __init__(self, messages, risks, workflows, outbox, gateway: AIGateway) -> None:
        self._messages = messages
        self._risks = risks
        self._workflows = workflows
        self._outbox = outbox
        self._gateway = gateway

    async def analyze_message(
        self,
        *,
        message_id: UUID,
        conversation_id: UUID,
        patient_id: UUID,
        organization_id: UUID,
        correlation_id: str | None,
        causation_id: str | None,
    ) -> RiskSignal:
        message = await self._messages.get_by_id(message_id)
        if message is None:
            raise NotFoundError(f"Message {message_id} not found for risk analysis")

        result = await self._gateway.complete(
            prompt_name="risk_signal",
            user_messages=[LLMMessage("user", message.content)],
            organization_id=organization_id,
            correlation_id=correlation_id,
            response_schema=RiskDraft,
        )
        draft: RiskDraft = result.structured
        now = datetime.now(UTC)
        signal = RiskSignal(
            id=uuid7(),
            organization_id=organization_id,
            conversation_id=conversation_id,
            message_id=message_id,
            patient_id=patient_id,
            category=draft.category,
            severity=draft.severity,
            confidence=draft.confidence,
            evidence=draft.evidence,
            model=result.model,
            prompt_version=1,
            ai_request_id=UUID(result.ai_request_id),
            simulated=result.simulated,
            created_at=now,
        )
        await self._risks.add_signal(signal)

        # Deterministic floor: crisis phrases in the raw message escalate to
        # human review even if the model (real, or steered by the message
        # itself) under classified. The model can only add escalations on
        # top of this floor, never remove them.
        escalate = escalation_required(signal.category, signal.severity) or (
            contains_crisis_language(message.content)
        )
        await self._outbox.add(
            domain_events.risk_signal_detected(
                risk_signal_id=signal.id,
                message_id=message_id,
                conversation_id=conversation_id,
                patient_id=patient_id,
                category=signal.category.value,
                severity=signal.severity,
                escalated=escalate,
                organization_id=organization_id,
                occurred_at=now,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        )
        if escalate:
            workflow_id = uuid7()
            await self._workflows.create(
                workflow_id=workflow_id,
                organization_id=organization_id,
                workflow_type=WorkflowType.RISK_ESCALATION,
                state=RiskEscalationState.PENDING_REVIEW,
                subject_id=signal.id,
                correlation_id=correlation_id,
                reason=f"risk signal {signal.category.value} severity {signal.severity}",
                now=now,
            )
            await self._outbox.add(
                domain_events.risk_review_required(
                    workflow_id=workflow_id,
                    risk_signal_id=signal.id,
                    patient_id=patient_id,
                    severity=signal.severity,
                    organization_id=organization_id,
                    occurred_at=now,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                )
            )
        return signal
