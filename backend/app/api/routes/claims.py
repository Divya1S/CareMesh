from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ClaimsServiceDep, CorrelationIdDep, CurrentUserDep
from app.api.schemas import (
    ClaimDecideRequest,
    ClaimResponse,
    ClaimResubmitRequest,
    ClaimSubmitRequest,
    EligibilityRequest,
    EligibilityResponse,
    OpsTransitionResponse,
)
from app.application.use_cases.claims import ClaimView

router = APIRouter(prefix="/claims", tags=["claims"])


def _claim(view: ClaimView) -> ClaimResponse:
    return ClaimResponse(
        claim_id=view.claim_id,
        workflow_id=view.workflow_id,
        patient_name=view.patient_name,
        description=view.description,
        amount_cents=view.amount_cents,
        member_id=view.member_id,
        plan_name=view.plan_name,
        state=view.state,
        denial_reason=view.denial_reason,
        resubmit_note=view.resubmit_note,
        created_at=view.created_at,
    )


@router.post("/eligibility", response_model=EligibilityResponse)
async def check_eligibility(
    body: EligibilityRequest, user: CurrentUserDep, service: ClaimsServiceDep
) -> EligibilityResponse:
    return EligibilityResponse(**await service.check_eligibility(user, body.member_id))


@router.get("", response_model=list[ClaimResponse])
async def list_claims(user: CurrentUserDep, service: ClaimsServiceDep) -> list[ClaimResponse]:
    return [_claim(v) for v in await service.list_claims(user)]


@router.post("", response_model=ClaimResponse, status_code=201)
async def submit_claim(
    body: ClaimSubmitRequest,
    user: CurrentUserDep,
    service: ClaimsServiceDep,
    correlation_id: CorrelationIdDep,
) -> ClaimResponse:
    view = await service.submit(
        user,
        patient_id=body.patient_id,
        description=body.description,
        amount_cents=body.amount_cents,
        eligibility_check_id=body.eligibility_check_id,
        correlation_id=correlation_id,
    )
    return _claim(view)


@router.get("/{claim_id}/history", response_model=list[OpsTransitionResponse])
async def claim_history(
    claim_id: UUID, user: CurrentUserDep, service: ClaimsServiceDep
) -> list[OpsTransitionResponse]:
    return [
        OpsTransitionResponse(
            from_state=t.from_state,
            to_state=t.to_state,
            actor=t.actor,
            reason=t.reason,
            occurred_at=t.occurred_at,
        )
        for t in await service.history(user, claim_id)
    ]


@router.post("/{claim_id}/decision", response_model=dict)
async def decide_claim(
    claim_id: UUID,
    body: ClaimDecideRequest,
    user: CurrentUserDep,
    service: ClaimsServiceDep,
    correlation_id: CorrelationIdDep,
) -> dict:
    state = await service.decide(user, claim_id, body.approve, body.denial_reason, correlation_id)
    return {"claim_id": str(claim_id), "state": state}


@router.post("/{claim_id}/resubmit", response_model=dict)
async def resubmit_claim(
    claim_id: UUID,
    body: ClaimResubmitRequest,
    user: CurrentUserDep,
    service: ClaimsServiceDep,
    correlation_id: CorrelationIdDep,
) -> dict:
    state = await service.resubmit(user, claim_id, body.note, correlation_id)
    return {"claim_id": str(claim_id), "state": state}
