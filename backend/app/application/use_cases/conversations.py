"""Conversation and message use cases with resource level authorization."""

from datetime import UTC, datetime
from uuid import UUID

from app.application import authorization as authz
from app.application.errors import NotFoundError
from app.application.ports import (
    CareAssignmentRepository,
    ConversationRepository,
    EventOutbox,
    MessageRepository,
)
from app.domain.entities import Conversation, Message, Role, SenderType, User
from app.domain.events import patient_message_created
from app.domain.ids import uuid7

MAX_PAGE_SIZE = 100


def _clamp_page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, MAX_PAGE_SIZE)), max(0, offset)


class ConversationService:
    def __init__(
        self,
        conversations: ConversationRepository,
        messages: MessageRepository,
        assignments: CareAssignmentRepository,
        outbox: EventOutbox,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._assignments = assignments
        self._outbox = outbox

    async def create_conversation(self, actor: User, title: str) -> Conversation:
        authz.ensure_can_create_conversation(actor)
        conversation = Conversation(
            id=uuid7(),
            organization_id=actor.organization_id,
            patient_id=actor.id,
            title=title.strip(),
            created_at=datetime.now(UTC),
        )
        await self._conversations.add(conversation)
        return conversation

    async def list_conversations(self, actor: User, limit: int, offset: int) -> list[Conversation]:
        authz.ensure_can_list_conversations(actor)
        limit, offset = _clamp_page(limit, offset)
        if actor.role is Role.PATIENT:
            return await self._conversations.list_for_patient(
                actor.organization_id, actor.id, limit, offset
            )
        patient_ids = await self._assignments.patient_ids_for_therapist(
            actor.organization_id, actor.id
        )
        if not patient_ids:
            return []
        return await self._conversations.list_for_patients(
            actor.organization_id, patient_ids, limit, offset
        )

    async def get_conversation(self, actor: User, conversation_id: UUID) -> Conversation:
        conversation = await self._conversations.get_by_id(conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found")
        assigned = await self._therapist_assigned(actor, conversation)
        authz.ensure_can_view_conversation(actor, conversation, assigned)
        return conversation

    async def list_messages(
        self, actor: User, conversation_id: UUID, limit: int, offset: int
    ) -> list[Message]:
        await self.get_conversation(actor, conversation_id)
        limit, offset = _clamp_page(limit, offset)
        return await self._messages.list_for_conversation(conversation_id, limit, offset)

    async def post_message(
        self,
        actor: User,
        conversation_id: UUID,
        content: str,
        correlation_id: str | None = None,
    ) -> Message:
        conversation = await self._conversations.get_by_id(conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found")
        assigned = await self._therapist_assigned(actor, conversation)
        authz.ensure_can_post_message(actor, conversation, assigned)
        message = Message(
            id=uuid7(),
            conversation_id=conversation.id,
            sender_type=(
                SenderType.PATIENT if actor.role is Role.PATIENT else SenderType.CLINICIAN
            ),
            sender_id=actor.id,
            content=content,
            created_at=datetime.now(UTC),
        )
        await self._messages.add(message)
        # Same transaction as the message write: the outbox relay publishes
        # this to the broker (ADR 0003), so there is no dual write.
        await self._outbox.add(
            patient_message_created(
                message_id=message.id,
                conversation_id=conversation.id,
                patient_id=conversation.patient_id,
                sender_type=message.sender_type.value,
                organization_id=conversation.organization_id,
                occurred_at=message.created_at,
                correlation_id=correlation_id,
            )
        )
        return message

    async def _therapist_assigned(self, actor: User, conversation: Conversation) -> bool:
        if actor.role is not Role.THERAPIST:
            return False
        return await self._assignments.is_assigned(actor.id, conversation.patient_id)
