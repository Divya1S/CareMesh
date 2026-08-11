from uuid import UUID

from fastapi import APIRouter

from app.api.deps import (
    CorrelationIdDep,
    CurrentUserDep,
    GuardianServiceDep,
    ReferralServiceDep,
)
from app.api.routes.school import _referral
from app.api.schemas import (
    GuardianOverviewResponse,
    GuardianUpdateRequest,
    ReferralDecideRequest,
    ReferralResponse,
)

router = APIRouter(tags=["guardian and referrals"])


@router.get("/guardian/overview", response_model=GuardianOverviewResponse)
async def guardian_overview(
    user: CurrentUserDep, service: GuardianServiceDep
) -> GuardianOverviewResponse:
    overview = await service.overview(user)
    return GuardianOverviewResponse(
        students=overview.students,
        updates=overview.updates,
        notifications=overview.notifications,
    )


@router.post("/guardian/updates", status_code=204)
async def share_guardian_update(
    body: GuardianUpdateRequest,
    user: CurrentUserDep,
    service: GuardianServiceDep,
    correlation_id: CorrelationIdDep,
) -> None:
    await service.share_update(user, body.patient_id, body.content, correlation_id)


@router.get("/my-patients", response_model=list[dict])
async def my_patients(user: CurrentUserDep, service: GuardianServiceDep) -> list[dict]:
    return await service.my_patients(user)


@router.get("/referrals", response_model=list[ReferralResponse])
async def pending_referrals(
    user: CurrentUserDep, service: ReferralServiceDep
) -> list[ReferralResponse]:
    return [_referral(v) for v in await service.list_pending(user)]


@router.post("/referrals/{referral_id}/decision", response_model=dict)
async def decide_referral(
    referral_id: UUID,
    body: ReferralDecideRequest,
    user: CurrentUserDep,
    service: ReferralServiceDep,
    correlation_id: CorrelationIdDep,
) -> dict:
    state = await service.decide(user, referral_id, body.accept, correlation_id)
    return {"referral_id": str(referral_id), "state": state}
