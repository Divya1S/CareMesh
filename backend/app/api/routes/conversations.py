import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import (
    ConversationServiceDep,
    CorrelationIdDep,
    CurrentUserDep,
    SessionDep,
    enforce_ai_rate_limit,
)
from app.api.schemas import (
    ConversationCreateRequest,
    ConversationResponse,
    MessageCreateRequest,
    MessageResponse,
)
from app.domain.entities import Conversation, Message

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _conversation(c: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=c.id, patient_id=c.patient_id, title=c.title, created_at=c.created_at
    )


def _message(m: Message) -> MessageResponse:
    return MessageResponse(
        id=m.id,
        conversation_id=m.conversation_id,
        sender_type=m.sender_type,
        sender_id=m.sender_id,
        content=m.content,
        created_at=m.created_at,
        simulated=m.simulated,
    )


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    body: ConversationCreateRequest,
    user: CurrentUserDep,
    service: ConversationServiceDep,
) -> ConversationResponse:
    return _conversation(await service.create_conversation(user, body.title))


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    user: CurrentUserDep,
    service: ConversationServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ConversationResponse]:
    return [_conversation(c) for c in await service.list_conversations(user, limit, offset)]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    user: CurrentUserDep,
    service: ConversationServiceDep,
) -> ConversationResponse:
    return _conversation(await service.get_conversation(user, conversation_id))


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID,
    user: CurrentUserDep,
    service: ConversationServiceDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[MessageResponse]:
    return [_message(m) for m in await service.list_messages(user, conversation_id, limit, offset)]


@router.post(
    "/{conversation_id}/messages/stream",
    dependencies=[Depends(enforce_ai_rate_limit)],
)
async def post_message_and_stream_reply(
    conversation_id: UUID,
    body: MessageCreateRequest,
    user: CurrentUserDep,
    service: ConversationServiceDep,
    session: SessionDep,
    correlation_id: CorrelationIdDep,
) -> StreamingResponse:
    """Saves the patient's message, then streams Dira's reply as SSE events:
    saved (the user message), tool, delta, message (the persisted reply),
    and error."""
    saved = await service.post_message(
        user, conversation_id, body.content, correlation_id, generate_reply=False
    )
    # Commit before the first byte streams: the request session's normal
    # commit happens after the response body finishes, so a mid stream
    # disconnect would otherwise roll back the message and its outbox
    # event after the client was already told it was saved.
    await session.commit()

    async def events():
        yield _sse({"type": "saved", "message": _message(saved).model_dump(mode="json")})
        async for event in service.stream_dira_reply(user, conversation_id, correlation_id):
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    dependencies=[Depends(enforce_ai_rate_limit)],
)
async def post_message(
    conversation_id: UUID,
    body: MessageCreateRequest,
    user: CurrentUserDep,
    service: ConversationServiceDep,
    correlation_id: CorrelationIdDep,
) -> MessageResponse:
    return _message(await service.post_message(user, conversation_id, body.content, correlation_id))
