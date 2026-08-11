from fastapi import APIRouter

from app.api.deps import CorrelationIdDep, CurrentUserDep, ReferralServiceDep
from app.api.schemas import ReferralResponse, ReferralSubmitRequest, RosterEntryResponse
from app.application.use_cases.referrals import ReferralView

router = APIRouter(prefix="/school", tags=["school"])


def _referral(view: ReferralView) -> ReferralResponse:
    return ReferralResponse(
        referral_id=view.referral_id,
        workflow_id=view.workflow_id,
        patient_id=view.patient_id,
        patient_name=view.patient_name,
        state=view.state,
        created_at=view.created_at,
        concern=view.concern,
    )


@router.get("/roster", response_model=list[RosterEntryResponse])
async def roster(user: CurrentUserDep, service: ReferralServiceDep) -> list[RosterEntryResponse]:
    return [
        RosterEntryResponse(patient_id=patient_id, name=name)
        for patient_id, name in await service.roster(user)
    ]


@router.get("/referrals", response_model=list[ReferralResponse])
async def my_referrals(user: CurrentUserDep, service: ReferralServiceDep) -> list[ReferralResponse]:
    return [_referral(v) for v in await service.list_mine(user)]


@router.post("/referrals", response_model=ReferralResponse, status_code=201)
async def submit_referral(
    body: ReferralSubmitRequest,
    user: CurrentUserDep,
    service: ReferralServiceDep,
    correlation_id: CorrelationIdDep,
) -> ReferralResponse:
    view = await service.submit(
        user, body.patient_id, body.concern, body.consent_confirmed, correlation_id
    )
    return _referral(view)
