from uuid import UUID

from fastapi import APIRouter

from app.api.deps import AppointmentServiceDep, CurrentUserDep

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.get("", response_model=list[dict])
async def pending_requests(user: CurrentUserDep, service: AppointmentServiceDep) -> list[dict]:
    return [
        {
            "request_id": str(v.request_id),
            "workflow_id": str(v.workflow_id),
            "patient_name": v.patient_name,
            "note": v.note,
            "state": v.state,
            "created_at": v.created_at.isoformat(),
        }
        for v in await service.list_pending(user)
    ]


@router.post("/{request_id}/acknowledge", response_model=dict)
async def acknowledge(
    request_id: UUID, user: CurrentUserDep, service: AppointmentServiceDep
) -> dict:
    state = await service.acknowledge(user, request_id)
    return {"request_id": str(request_id), "state": state}
