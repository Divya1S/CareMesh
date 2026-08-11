"""The clinician review queue and decision use cases. An AI signal becomes
care relevant only through an explicit, audited human decision here."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.application.errors import DomainValidationError, ForbiddenError, NotFoundError
from app.domain import events as domain_events
from app.domain.entities import Role, User
from app.domain.ids import uuid7
from app.domain.risk import ReviewDecision, RiskReview, RiskSignal
from app.domain.workflows import RiskEscalationState, validate_transition


@dataclass(frozen=True, slots=True)
class ReviewQueueItem:
    workflow_id: UUID
    signal: RiskSignal
    patient_name: str
    message_content: str


class ReviewService:
    def __init__(self, workflows, risks, assignments, users, messages, outbox, audit) -> None:
        self._workflows = workflows
        self._risks = risks
        self._assignments = assignments
        self._users = users
        self._messages = messages
        self._outbox = outbox
        self._audit = audit

    async def list_pending(self, actor: User) -> list[ReviewQueueItem]:
        self._ensure_therapist(actor)
        patient_ids = await self._assignments.patient_ids_for_therapist(
            actor.organization_id, actor.id
        )
        if not patient_ids:
            return []
        pending = await self._workflows.list_pending_risk(actor.organization_id, patient_ids)
        items: list[ReviewQueueItem] = []
        for workflow, signal in pending:
            patient = await self._users.get_by_id(signal.patient_id)
            message = await self._messages.get_by_id(signal.message_id)
            items.append(
                ReviewQueueItem(
                    workflow_id=workflow.id,
                    signal=signal,
                    patient_name=patient.display_name if patient else "Unknown",
                    message_content=message.content if message else "",
                )
            )
        return items

    async def decide(
        self,
        actor: User,
        workflow_id: UUID,
        decision: ReviewDecision,
        severity_override: int | None,
        note: str,
        correlation_id: str | None,
    ) -> str:
        self._ensure_therapist(actor)
        workflow = await self._workflows.get_by_id(workflow_id)
        if workflow is None or workflow.organization_id != actor.organization_id:
            raise NotFoundError("Review not found")
        signal = await self._risks.get_signal(workflow.subject_id)
        if signal is None:
            raise NotFoundError("Risk signal not found")
        if not await self._assignments.is_assigned(actor.id, signal.patient_id):
            raise ForbiddenError("You are not assigned to this patient")
        if workflow.state != RiskEscalationState.PENDING_REVIEW:
            raise DomainValidationError("This review is already resolved")
        if decision is ReviewDecision.EDIT and severity_override is None:
            raise DomainValidationError("Editing a signal requires a severity override")

        now = datetime.now(UTC)
        validate_transition(workflow.workflow_type, workflow.state, RiskEscalationState.RESOLVED)
        await self._risks.add_review(
            RiskReview(
                id=uuid7(),
                organization_id=actor.organization_id,
                risk_signal_id=signal.id,
                reviewer_id=actor.id,
                decision=decision,
                severity_override=severity_override,
                note=note,
                created_at=now,
            )
        )
        await self._workflows.transition(
            workflow_id=workflow.id,
            from_state=workflow.state,
            to_state=RiskEscalationState.RESOLVED,
            actor=str(actor.id),
            reason=f"review {decision.value}",
            now=now,
        )
        await self._audit.record(
            action="review_decided",
            organization_id=actor.organization_id,
            actor_id=actor.id,
            resource_type="risk_signal",
            resource_id=signal.id,
            detail={"decision": decision.value, "severity_override": severity_override},
        )
        await self._outbox.add(
            domain_events.human_review_completed(
                workflow_id=workflow.id,
                risk_signal_id=signal.id,
                reviewer_id=actor.id,
                decision=decision.value,
                severity_override=severity_override,
                organization_id=actor.organization_id,
                occurred_at=now,
                correlation_id=correlation_id,
            )
        )
        return RiskEscalationState.RESOLVED.value

    @staticmethod
    def _ensure_therapist(actor: User) -> None:
        if actor.role is not Role.THERAPIST:
            raise ForbiddenError("Only therapists review risk signals")
