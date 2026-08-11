"""School referrals: a real workflow from a school concern to a care team
decision. Least privilege is structural: school staff see roster names and
their own referrals' states, never conversations, signals, or care details."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.application.errors import DomainValidationError, ForbiddenError, NotFoundError
from app.domain import events as domain_events
from app.domain.entities import CareAssignment, Role, User
from app.domain.ids import uuid7
from app.domain.workflows import ReferralState, WorkflowType, validate_transition


@dataclass(frozen=True, slots=True)
class ReferralView:
    referral_id: UUID
    workflow_id: UUID
    patient_id: UUID
    patient_name: str
    state: str
    created_at: datetime
    # Only populated for roles allowed to read it (submitter and therapists).
    concern: str | None


class ReferralService:
    def __init__(self, referrals, workflows, users, assignments, guardians, outbox) -> None:
        self._referrals = referrals
        self._workflows = workflows
        self._users = users
        self._assignments = assignments
        self._guardians = guardians
        self._outbox = outbox

    async def roster(self, actor: User) -> list[tuple[UUID, str]]:
        """Names only. The roster is the whole of what a school sees about
        students outside their own referrals."""
        self._ensure(actor, Role.SCHOOL_STAFF)
        return await self._users.list_patients(actor.organization_id)

    async def submit(
        self,
        actor: User,
        patient_id: UUID,
        concern: str,
        consent_confirmed: bool,
        correlation_id: str | None,
    ) -> ReferralView:
        self._ensure(actor, Role.SCHOOL_STAFF)
        if not consent_confirmed:
            raise DomainValidationError(
                "Confirm that the student or their guardian consents to this referral"
            )
        patient = await self._users.get_by_id(patient_id)
        if (
            patient is None
            or patient.organization_id != actor.organization_id
            or patient.role is not Role.PATIENT
        ):
            raise NotFoundError("Student not found")

        now = datetime.now(UTC)
        referral_id = uuid7()
        workflow_id = uuid7()
        await self._workflows.create(
            workflow_id=workflow_id,
            organization_id=actor.organization_id,
            workflow_type=WorkflowType.REFERRAL,
            state=ReferralState.SUBMITTED,
            subject_id=referral_id,
            correlation_id=correlation_id,
            reason=f"referral submitted by {actor.id}",
            now=now,
        )
        await self._referrals.add(
            referral_id=referral_id,
            organization_id=actor.organization_id,
            patient_id=patient_id,
            submitted_by=actor.id,
            workflow_id=workflow_id,
            concern=concern.strip(),
            consent_confirmed=consent_confirmed,
            created_at=now,
        )
        await self._outbox.add(
            domain_events.referral_submitted(
                referral_id=referral_id,
                workflow_id=workflow_id,
                patient_id=patient_id,
                submitted_by=actor.id,
                organization_id=actor.organization_id,
                occurred_at=now,
                correlation_id=correlation_id,
            )
        )
        return ReferralView(
            referral_id=referral_id,
            workflow_id=workflow_id,
            patient_id=patient_id,
            patient_name=patient.display_name,
            state=ReferralState.SUBMITTED.value,
            created_at=now,
            concern=concern.strip(),
        )

    async def list_mine(self, actor: User) -> list[ReferralView]:
        self._ensure(actor, Role.SCHOOL_STAFF)
        rows = await self._referrals.list_joined(actor.organization_id, submitted_by=actor.id)
        return [self._view(r, s, name, include_concern=True) for r, s, name in rows]

    async def list_pending(self, actor: User) -> list[ReferralView]:
        self._ensure(actor, Role.THERAPIST)
        rows = await self._referrals.list_joined(
            actor.organization_id, state=ReferralState.SUBMITTED.value
        )
        return [self._view(r, s, name, include_concern=True) for r, s, name in rows]

    async def decide(
        self, actor: User, referral_id: UUID, accept: bool, correlation_id: str | None
    ) -> str:
        self._ensure(actor, Role.THERAPIST)
        referral = await self._referrals.get_by_id(referral_id)
        if referral is None or referral.organization_id != actor.organization_id:
            raise NotFoundError("Referral not found")
        workflow = await self._workflows.get_by_id(referral.workflow_id)
        if workflow.state != ReferralState.SUBMITTED:
            raise DomainValidationError("This referral is already decided")

        target = ReferralState.ACCEPTED if accept else ReferralState.DECLINED
        validate_transition(WorkflowType.REFERRAL, workflow.state, target)
        now = datetime.now(UTC)
        await self._workflows.transition(
            workflow_id=workflow.id,
            from_state=workflow.state,
            to_state=target,
            actor=str(actor.id),
            reason=f"referral {target.value}",
            now=now,
        )
        if accept and not await self._assignments.is_assigned(actor.id, referral.patient_id):
            await self._assignments.add(
                CareAssignment(
                    id=uuid7(),
                    organization_id=actor.organization_id,
                    therapist_id=actor.id,
                    patient_id=referral.patient_id,
                    created_at=now,
                )
            )
        await self._outbox.add(
            domain_events.referral_decided(
                referral_id=referral.id,
                workflow_id=workflow.id,
                patient_id=referral.patient_id,
                decided_by=actor.id,
                decision=target.value,
                organization_id=actor.organization_id,
                occurred_at=now,
                correlation_id=correlation_id,
            )
        )
        if accept:
            await self._notify_guardians(actor, referral.patient_id, now, correlation_id)
        return target.value

    async def _notify_guardians(
        self, actor: User, patient_id: UUID, now: datetime, correlation_id: str | None
    ) -> None:
        patient = await self._users.get_by_id(patient_id)
        name = patient.display_name if patient else "your student"
        for guardian_id in await self._guardians.guardians_for_patient(patient_id):
            notification_id = await self._guardians.add_notification(
                organization_id=actor.organization_id,
                guardian_id=guardian_id,
                patient_id=patient_id,
                kind="referral_accepted",
                content=(
                    f"The care team accepted a school referral for {name} and will reach out soon."
                ),
                now=now,
            )
            await self._outbox.add(
                domain_events.guardian_notification_required(
                    notification_id=notification_id,
                    guardian_id=guardian_id,
                    patient_id=patient_id,
                    kind="referral_accepted",
                    organization_id=actor.organization_id,
                    occurred_at=now,
                    correlation_id=correlation_id,
                )
            )

    def _view(self, row, state: str, patient_name: str, include_concern: bool) -> ReferralView:
        return ReferralView(
            referral_id=row.id,
            workflow_id=row.workflow_id,
            patient_id=row.patient_id,
            patient_name=patient_name,
            state=state,
            created_at=row.created_at,
            concern=row.concern if include_concern else None,
        )

    @staticmethod
    def _ensure(actor: User, role: Role) -> None:
        if actor.role is not role:
            raise ForbiddenError(f"This action requires the {role.value} role")
