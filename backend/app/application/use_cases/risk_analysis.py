"""Risk analysis: AI produces a structured signal, deterministic code
decides whether a human review workflow starts.

Two steps on purpose. RiskClassifier.classify talks to the model and holds
no database transaction. RiskAnalysisService.record writes the signal, the
escalation decision, and the workflow in the caller's transaction, next to
the consumer's idempotency mark.

The deterministic crisis phrase floor is evaluated before the model is
called. A provider outage, timeout, or malformed output can therefore never
silence an explicit crisis disclosure: when the floor matches and the model
cannot answer, the floor opens the review workflow on its own, and the
gateway has already audited the failed call.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.application.ai.gateway import AIGateway, AIProviderError
from app.application.ai.types import LLMMessage
from app.application.errors import AppError
from app.domain import events as domain_events
from app.domain.ids import uuid7
from app.domain.risk import (
    CRISIS_FLOOR_MODEL,
    RiskCategory,
    RiskSignal,
    escalation_required,
    matched_crisis_phrase,
)
from app.domain.workflows import RiskEscalationState, WorkflowType


class RiskDraft(BaseModel):
    """What the risk_signal prompt must return. Validated by the gateway."""

    category: RiskCategory
    severity: int = Field(ge=0, le=3)
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(max_length=500)


@dataclass(frozen=True, slots=True)
class RiskClassification:
    """The outcome of classify(): the model's draft when it answered, or a
    floor only result when it could not and the message tripped the floor."""

    draft: RiskDraft | None
    model: str
    prompt_version: int
    ai_request_id: UUID | None
    simulated: bool
    # The crisis phrase that matched, if any. Set independently of the model.
    crisis_phrase: str | None
    # The gateway error class when the model could not answer.
    model_error: str | None

    @property
    def floor_only(self) -> bool:
        return self.draft is None


class RiskClassifier:
    """Model access for risk analysis. Holds no repositories, so callers can
    run it outside any database transaction."""

    def __init__(self, gateway: AIGateway) -> None:
        self._gateway = gateway

    async def classify(
        self, *, content: str, organization_id: UUID, correlation_id: str | None
    ) -> RiskClassification:
        phrase = matched_crisis_phrase(content)
        try:
            result = await self._gateway.complete(
                prompt_name="risk_signal",
                user_messages=[LLMMessage("user", content)],
                organization_id=organization_id,
                correlation_id=correlation_id,
                response_schema=RiskDraft,
            )
        except AppError as exc:
            if phrase is None:
                # No floor match: the caller retries and dead letters as
                # before, and nothing is recorded for this attempt.
                raise
            return RiskClassification(
                draft=None,
                model=CRISIS_FLOOR_MODEL,
                prompt_version=0,
                ai_request_id=None,
                simulated=False,
                crisis_phrase=phrase,
                model_error=type(exc).__name__,
            )
        draft = result.structured
        if not isinstance(draft, RiskDraft):
            raise AIProviderError("risk_signal returned no structured output")
        return RiskClassification(
            draft=draft,
            model=result.model,
            prompt_version=result.prompt_version,
            ai_request_id=UUID(result.ai_request_id),
            simulated=result.simulated,
            crisis_phrase=phrase,
            model_error=None,
        )


class RiskAnalysisService:
    """Writes the signal and the escalation decision. Runs in the caller's
    transaction, which in the consumer also holds the idempotency mark."""

    def __init__(self, risks, workflows, outbox) -> None:
        self._risks = risks
        self._workflows = workflows
        self._outbox = outbox

    async def record(
        self,
        *,
        classification: RiskClassification,
        message_id: UUID,
        conversation_id: UUID,
        patient_id: UUID,
        organization_id: UUID,
        correlation_id: str | None,
        causation_id: str | None,
    ) -> RiskSignal:
        now = datetime.now(UTC)
        draft = classification.draft
        if draft is not None:
            category, severity = draft.category, draft.severity
            confidence, evidence = draft.confidence, draft.evidence
        else:
            # Floor only: the phrase itself is the evidence, and the
            # severity is the maximum because a human must look at it.
            category, severity, confidence = RiskCategory.CRISIS, 3, 1.0
            evidence = classification.crisis_phrase or ""
        signal = RiskSignal(
            id=uuid7(),
            organization_id=organization_id,
            conversation_id=conversation_id,
            message_id=message_id,
            patient_id=patient_id,
            category=category,
            severity=severity,
            confidence=confidence,
            evidence=evidence,
            model=classification.model,
            prompt_version=classification.prompt_version,
            ai_request_id=classification.ai_request_id,
            simulated=classification.simulated,
            created_at=now,
        )
        await self._risks.add_signal(signal)

        # The model can only add escalations on top of the deterministic
        # floor, never remove them.
        escalate = (
            escalation_required(signal.category, signal.severity)
            or classification.crisis_phrase is not None
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
            reason = f"risk signal {signal.category.value} severity {signal.severity}"
            if classification.floor_only:
                reason += f" (crisis phrase floor, model {classification.model_error})"
            await self._workflows.create(
                workflow_id=workflow_id,
                organization_id=organization_id,
                workflow_type=WorkflowType.RISK_ESCALATION,
                state=RiskEscalationState.PENDING_REVIEW,
                subject_id=signal.id,
                correlation_id=correlation_id,
                reason=reason,
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
