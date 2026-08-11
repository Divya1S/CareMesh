from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CorrelationIdDep, CurrentUserDep, ReviewServiceDep
from app.api.schemas import (
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueueItemResponse,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("", response_model=list[ReviewQueueItemResponse])
async def list_pending_reviews(
    user: CurrentUserDep, service: ReviewServiceDep
) -> list[ReviewQueueItemResponse]:
    items = await service.list_pending(user)
    return [
        ReviewQueueItemResponse(
            workflow_id=item.workflow_id,
            risk_signal_id=item.signal.id,
            patient_name=item.patient_name,
            message_content=item.message_content,
            category=item.signal.category,
            severity=item.signal.severity,
            confidence=item.signal.confidence,
            evidence=item.signal.evidence,
            model=item.signal.model,
            prompt_version=item.signal.prompt_version,
            simulated=item.signal.simulated,
            created_at=item.signal.created_at,
        )
        for item in items
    ]


@router.post("/{workflow_id}", response_model=ReviewDecisionResponse)
async def decide_review(
    workflow_id: UUID,
    body: ReviewDecisionRequest,
    user: CurrentUserDep,
    service: ReviewServiceDep,
    correlation_id: CorrelationIdDep,
) -> ReviewDecisionResponse:
    state = await service.decide(
        user, workflow_id, body.decision, body.severity_override, body.note, correlation_id
    )
    return ReviewDecisionResponse(workflow_id=workflow_id, state=state, decision=body.decision)
