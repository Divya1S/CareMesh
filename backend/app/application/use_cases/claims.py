"""The revenue cycle, simplified but real: eligibility through a labeled
payer adapter, claim submission by the treating therapist, payer review
with tracked denial reasons, and resubmission. Every state change is a
validated workflow transition with an event."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.application.errors import DomainValidationError, ForbiddenError, NotFoundError
from app.domain import events as domain_events
from app.domain.entities import Role, User
from app.domain.ids import uuid7
from app.domain.workflows import ClaimState, WorkflowType, validate_transition
from app.infrastructure.payer.fake_payer import PayerAdapter


@dataclass(frozen=True, slots=True)
class ClaimView:
    claim_id: UUID
    workflow_id: UUID
    patient_name: str
    description: str
    amount_cents: int
    member_id: str
    plan_name: str
    state: str
    denial_reason: str | None
    resubmit_note: str | None
    created_at: datetime


class ClaimsService:
    def __init__(
        self, claims, workflows, assignments, adapter: PayerAdapter, outbox, audit
    ) -> None:
        self._claims = claims
        self._workflows = workflows
        self._assignments = assignments
        self._adapter = adapter
        self._outbox = outbox
        self._audit = audit

    async def check_eligibility(self, actor: User, member_id: str) -> dict:
        self._ensure(actor, Role.THERAPIST)
        result = self._adapter.check_eligibility(member_id)
        check_id = uuid7()
        await self._claims.add_eligibility_check(
            check_id=check_id,
            organization_id=actor.organization_id,
            member_id=member_id.strip(),
            eligible=result.eligible,
            plan_name=result.plan_name,
            adapter=result.adapter,
            simulated=result.simulated,
            checked_by=actor.id,
            now=datetime.now(UTC),
        )
        return {
            "eligibility_check_id": str(check_id),
            "eligible": result.eligible,
            "plan_name": result.plan_name,
            "adapter": result.adapter,
            "simulated": result.simulated,
        }

    async def submit(
        self,
        actor: User,
        *,
        patient_id: UUID,
        description: str,
        amount_cents: int,
        eligibility_check_id: UUID,
        correlation_id: str | None,
    ) -> ClaimView:
        self._ensure(actor, Role.THERAPIST)
        if not await self._assignments.is_assigned(actor.id, patient_id):
            raise ForbiddenError("You can only bill for your assigned patients")
        check = await self._claims.get_eligibility_check(eligibility_check_id)
        if check is None or check.organization_id != actor.organization_id:
            raise NotFoundError("Eligibility check not found")
        if not check.eligible:
            raise DomainValidationError("This member is not eligible; the claim would be rejected")

        now = datetime.now(UTC)
        claim_id = uuid7()
        workflow_id = uuid7()
        await self._workflows.create(
            workflow_id=workflow_id,
            organization_id=actor.organization_id,
            workflow_type=WorkflowType.CLAIM,
            state=ClaimState.SUBMITTED,
            subject_id=claim_id,
            correlation_id=correlation_id,
            reason=f"claim submitted by {actor.id}",
            now=now,
        )
        await self._claims.add(
            id=claim_id,
            organization_id=actor.organization_id,
            patient_id=patient_id,
            submitted_by=actor.id,
            workflow_id=workflow_id,
            eligibility_check_id=eligibility_check_id,
            description=description.strip(),
            amount_cents=amount_cents,
            member_id=check.member_id,
            plan_name=check.plan_name,
            denial_reason=None,
            resubmit_note=None,
            created_at=now,
        )
        await self._outbox.add(
            domain_events.insurance_claim_submitted(
                claim_id=claim_id,
                workflow_id=workflow_id,
                patient_id=patient_id,
                submitted_by=actor.id,
                amount_cents=amount_cents,
                organization_id=actor.organization_id,
                occurred_at=now,
                correlation_id=correlation_id,
            )
        )
        rows = await self._claims.list_joined(actor.organization_id, submitted_by=actor.id)
        for row, state, name in rows:
            if row.id == claim_id:
                return self._view(row, state, name)
        raise NotFoundError("Claim not found after creation")

    async def list_claims(self, actor: User) -> list[ClaimView]:
        if actor.role is Role.PAYER_STAFF:
            rows = await self._claims.list_joined(actor.organization_id)
        elif actor.role is Role.THERAPIST:
            rows = await self._claims.list_joined(actor.organization_id, submitted_by=actor.id)
        else:
            raise ForbiddenError("Your role has no access to claims")
        return [self._view(row, state, name) for row, state, name in rows]

    async def history(self, actor: User, claim_id: UUID) -> list:
        claim = await self._load(actor, claim_id)
        if actor.role is Role.THERAPIST and claim.submitted_by != actor.id:
            raise ForbiddenError("Not your claim")
        if actor.role not in (Role.PAYER_STAFF, Role.THERAPIST):
            raise ForbiddenError("Your role has no access to claims")
        return await self._workflows.transitions_for(claim.workflow_id)

    async def decide(
        self,
        actor: User,
        claim_id: UUID,
        approve: bool,
        denial_reason: str | None,
        correlation_id: str | None,
    ) -> str:
        self._ensure(actor, Role.PAYER_STAFF)
        claim = await self._load(actor, claim_id)
        workflow = await self._workflows.get_by_id(claim.workflow_id)
        if workflow.state not in (ClaimState.SUBMITTED, ClaimState.RESUBMITTED):
            raise DomainValidationError("This claim is not awaiting review")
        if not approve and not (denial_reason and denial_reason.strip()):
            raise DomainValidationError("Denials must carry a reason; that is the point")
        target = ClaimState.APPROVED if approve else ClaimState.DENIED
        validate_transition(WorkflowType.CLAIM, workflow.state, target)
        now = datetime.now(UTC)
        await self._workflows.transition(
            workflow_id=workflow.id,
            from_state=workflow.state,
            to_state=target,
            actor=str(actor.id),
            reason=denial_reason.strip() if denial_reason else f"claim {target.value}",
            now=now,
        )
        await self._claims.set_denial_reason(
            claim.id, denial_reason.strip() if not approve and denial_reason else None
        )
        await self._audit.record(
            action="claim_decided",
            organization_id=actor.organization_id,
            actor_id=actor.id,
            resource_type="claim",
            resource_id=claim.id,
            detail={"decision": target.value},
        )
        await self._outbox.add(
            domain_events.insurance_claim_updated(
                claim_id=claim.id,
                workflow_id=workflow.id,
                state=target.value,
                actor_id=actor.id,
                organization_id=actor.organization_id,
                occurred_at=now,
                correlation_id=correlation_id,
            )
        )
        return target.value

    async def resubmit(
        self, actor: User, claim_id: UUID, note: str, correlation_id: str | None
    ) -> str:
        self._ensure(actor, Role.THERAPIST)
        claim = await self._load(actor, claim_id)
        if claim.submitted_by != actor.id:
            raise ForbiddenError("Not your claim")
        workflow = await self._workflows.get_by_id(claim.workflow_id)
        validate_transition(WorkflowType.CLAIM, workflow.state, ClaimState.RESUBMITTED)
        now = datetime.now(UTC)
        await self._workflows.transition(
            workflow_id=workflow.id,
            from_state=workflow.state,
            to_state=ClaimState.RESUBMITTED,
            actor=str(actor.id),
            reason=f"resubmitted: {note.strip()[:100]}",
            now=now,
        )
        await self._claims.set_resubmit_note(claim.id, note.strip())
        await self._outbox.add(
            domain_events.insurance_claim_updated(
                claim_id=claim.id,
                workflow_id=workflow.id,
                state=ClaimState.RESUBMITTED.value,
                actor_id=actor.id,
                organization_id=actor.organization_id,
                occurred_at=now,
                correlation_id=correlation_id,
            )
        )
        return ClaimState.RESUBMITTED.value

    async def _load(self, actor: User, claim_id: UUID):
        claim = await self._claims.get_by_id(claim_id)
        if claim is None or claim.organization_id != actor.organization_id:
            raise NotFoundError("Claim not found")
        return claim

    @staticmethod
    def _view(row, state: str, patient_name: str) -> ClaimView:
        return ClaimView(
            claim_id=row.id,
            workflow_id=row.workflow_id,
            patient_name=patient_name,
            description=row.description,
            amount_cents=row.amount_cents,
            member_id=row.member_id,
            plan_name=row.plan_name,
            state=state,
            denial_reason=row.denial_reason,
            resubmit_note=row.resubmit_note,
            created_at=row.created_at,
        )

    @staticmethod
    def _ensure(actor: User, role: Role) -> None:
        if actor.role is not role:
            raise ForbiddenError(f"This action requires the {role.value} role")
