from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, OpsServiceDep, SettingsDep
from app.api.schemas import (
    OpsAIRequestDetailResponse,
    OpsAIRequestResponse,
    OpsDlqResponse,
    OpsEventResponse,
    OpsTransitionResponse,
    OpsWorkflowDetailResponse,
    OpsWorkflowResponse,
)
from app.application.use_cases.ops import ensure_ops
from app.domain.events import PATIENT_MESSAGE_CREATED
from app.infrastructure.events.dlq import read_dlq
from app.infrastructure.events.schemas import dlq_topic_for, topic_for

router = APIRouter(prefix="/ops", tags=["ops"])


def _workflow(w) -> OpsWorkflowResponse:
    return OpsWorkflowResponse(
        id=w.id,
        workflow_type=w.workflow_type.value,
        state=w.state,
        subject_id=w.subject_id,
        correlation_id=w.correlation_id,
        created_at=w.created_at,
        updated_at=w.updated_at,
    )


def _ai_request(row, detail: bool = False) -> OpsAIRequestResponse:
    base = {
        "id": row.id,
        "provider": row.provider,
        "model": row.model,
        "prompt_name": row.prompt_name,
        "prompt_version": row.prompt_version,
        "status": row.status,
        "simulated": row.simulated,
        "validation_ok": row.validation_ok,
        "latency_ms": row.latency_ms,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cost_usd": row.cost_usd,
        "correlation_id": row.correlation_id,
        "error_type": row.error_type,
        "created_at": row.created_at,
    }
    if detail:
        return OpsAIRequestDetailResponse(
            **base, request_messages=row.request_messages, response_text=row.response_text
        )
    return OpsAIRequestResponse(**base)


@router.get("/workflows", response_model=list[OpsWorkflowResponse])
async def list_workflows(
    user: CurrentUserDep,
    service: OpsServiceDep,
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OpsWorkflowResponse]:
    return [_workflow(w) for w in await service.list_workflows(user, state, limit)]


@router.get("/workflows/{workflow_id}", response_model=OpsWorkflowDetailResponse)
async def workflow_detail(
    workflow_id: UUID, user: CurrentUserDep, service: OpsServiceDep
) -> OpsWorkflowDetailResponse:
    workflow, transitions = await service.workflow_detail(user, workflow_id)
    return OpsWorkflowDetailResponse(
        workflow=_workflow(workflow),
        transitions=[
            OpsTransitionResponse(
                from_state=t.from_state,
                to_state=t.to_state,
                actor=t.actor,
                reason=t.reason,
                occurred_at=t.occurred_at,
            )
            for t in transitions
        ],
    )


@router.get("/ai-requests", response_model=list[OpsAIRequestResponse])
async def list_ai_requests(
    user: CurrentUserDep,
    service: OpsServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OpsAIRequestResponse]:
    return [_ai_request(r) for r in await service.list_ai_requests(user, limit)]


@router.get("/ai-requests/{request_id}", response_model=OpsAIRequestDetailResponse)
async def ai_request_detail(
    request_id: UUID, user: CurrentUserDep, service: OpsServiceDep
) -> OpsAIRequestDetailResponse:
    return _ai_request(await service.ai_request_detail(user, request_id), detail=True)


@router.get("/events", response_model=list[OpsEventResponse])
async def list_events(
    user: CurrentUserDep,
    service: OpsServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OpsEventResponse]:
    return [
        OpsEventResponse(
            id=e.id,
            event_type=e.event_type,
            schema_version=e.schema_version,
            occurred_at=e.occurred_at,
            published_at=e.published_at,
            correlation_id=e.correlation_id,
        )
        for e in await service.list_events(user, limit)
    ]


@router.post("/events/{event_id}/republish", status_code=204)
async def republish_event(event_id: UUID, user: CurrentUserDep, service: OpsServiceDep) -> None:
    await service.republish_event(user, event_id)


@router.get("/dlq", response_model=OpsDlqResponse)
async def view_dlq(user: CurrentUserDep, settings: SettingsDep) -> OpsDlqResponse:
    ensure_ops(user)
    topic = dlq_topic_for(topic_for(settings.kafka_topic_prefix, PATIENT_MESSAGE_CREATED))
    records = await read_dlq(topic, settings.kafka_bootstrap_servers)
    # Raw payload previews; malformed events may hold clinical text, so the
    # preview is truncated hard.
    return OpsDlqResponse(topic=topic, records=[r[:200].decode(errors="replace") for r in records])
