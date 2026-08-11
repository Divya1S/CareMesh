"""Conversation and message use cases with resource level authorization."""

import json
from datetime import UTC, datetime
from uuid import UUID

from app.application import authorization as authz
from app.application.ai.gateway import AIGateway
from app.application.ai.tools import Tool, ToolResult
from app.application.ai.types import LLMMessage, ToolDef
from app.application.errors import AppError, ForbiddenError, NotFoundError
from app.application.ports import (
    CareAssignmentRepository,
    ConversationRepository,
    EventOutbox,
    MessageRepository,
)
from app.domain.entities import Conversation, Message, Role, SenderType, User
from app.domain.events import (
    ai_response_generated,
    appointment_requested,
    patient_message_created,
)
from app.domain.ids import uuid7
from app.domain.risk import contains_crisis_language
from app.domain.workflows import AppointmentRequestState, WorkflowType

# How much conversation history Dira sees. Enough for continuity in S5;
# revisited when conversations grow long.
DIRA_MEMORY_MESSAGES = 12

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
        gateway: AIGateway,
        knowledge=None,
        appointments=None,
        workflows=None,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._assignments = assignments
        self._outbox = outbox
        self._gateway = gateway
        self._knowledge = knowledge
        self._appointments = appointments
        self._workflows = workflows

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
        generate_reply: bool = True,
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
        if generate_reply and actor.role is Role.PATIENT:
            await self._generate_dira_reply(conversation, correlation_id)
        return message

    async def _build_history(self, conversation: Conversation) -> list[LLMMessage]:
        history = await self._messages.list_for_conversation(conversation.id, 100, 0)
        llm_messages: list[LLMMessage] = []
        for m in history[-DIRA_MEMORY_MESSAGES:]:
            if m.sender_type is SenderType.DIRA:
                llm_messages.append(LLMMessage("assistant", m.content))
            elif m.sender_type is SenderType.CLINICIAN:
                llm_messages.append(LLMMessage("user", f"(from the care team) {m.content}"))
            else:
                llm_messages.append(LLMMessage("user", m.content))
        return llm_messages

    def _dira_tools(self, conversation: Conversation, correlation_id: str | None) -> list[Tool]:
        """Dira's allow listed tools (ADR 0007). Handlers carry the
        conversation's authorization context; the model only picks."""
        if self._knowledge is None or self._appointments is None:
            return []

        async def search_resources(arguments: dict) -> ToolResult:
            query = str(arguments.get("query", ""))[:200]
            chunks = await self._knowledge.retrieve(conversation.organization_id, query)
            results = [
                {
                    "title": c.document_title,
                    "snippet": c.chunk.content[:220],
                    "chunk_id": str(c.chunk.id),
                }
                for c in chunks
            ]
            return ToolResult(
                content=json.dumps(results),
                summary="Dira searched the resource library",
                payload={"citations": results},
            )

        async def request_appointment(arguments: dict) -> ToolResult:
            # Idempotent per conversation: a model asking repeatedly (or a
            # steered model asking many times in one turn) creates at most
            # one open request for the care team.
            if await self._appointments.has_open_for_conversation(
                conversation.id, AppointmentRequestState.REQUESTED.value
            ):
                return ToolResult(
                    content=(
                        "An appointment request from this conversation is "
                        "already waiting for the care team."
                    ),
                    summary="An appointment request is already pending",
                )
            note = str(arguments.get("note", ""))[:500]
            now = datetime.now(UTC)
            request_id = uuid7()
            workflow_id = uuid7()
            await self._workflows.create(
                workflow_id=workflow_id,
                organization_id=conversation.organization_id,
                workflow_type=WorkflowType.APPOINTMENT_REQUEST,
                state=AppointmentRequestState.REQUESTED,
                subject_id=request_id,
                correlation_id=correlation_id,
                reason="requested through Dira",
                now=now,
            )
            await self._appointments.add(
                request_id=request_id,
                organization_id=conversation.organization_id,
                patient_id=conversation.patient_id,
                conversation_id=conversation.id,
                workflow_id=workflow_id,
                note=note,
                created_at=now,
            )
            await self._outbox.add(
                appointment_requested(
                    appointment_request_id=request_id,
                    workflow_id=workflow_id,
                    patient_id=conversation.patient_id,
                    conversation_id=conversation.id,
                    organization_id=conversation.organization_id,
                    occurred_at=now,
                    correlation_id=correlation_id,
                )
            )
            return ToolResult(
                content="The care team has been notified of the appointment request.",
                summary="Dira asked the care team for an appointment",
            )

        return [
            Tool(
                definition=ToolDef(
                    name="search_resources",
                    description=(
                        "Search the organization's resource library for "
                        "wellbeing information relevant to the student's question."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                ),
                run=search_resources,
            ),
            Tool(
                definition=ToolDef(
                    name="request_appointment",
                    description=(
                        "Tell the care team the student would like an "
                        "appointment. Never books anything itself."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {"note": {"type": "string"}},
                        "required": ["note"],
                    },
                ),
                run=request_appointment,
                mutates=True,
            ),
        ]

    def _tools_for_turn(
        self,
        conversation: Conversation,
        correlation_id: str | None,
        llm_messages: list[LLMMessage],
    ) -> list[Tool]:
        """Crisis precedence, enforced structurally: when the latest patient
        message contains crisis language, Dira gets no tools at all this
        turn, so no model (real or fake) can detour into a search or an
        appointment instead of the direct crisis reply. Provider independent
        on purpose; the fake provider's scenario logic is not the guarantee."""
        last_user = next((m.content for m in reversed(llm_messages) if m.role == "user"), "")
        if contains_crisis_language(last_user):
            return []
        return self._dira_tools(conversation, correlation_id)

    async def _persist_dira_reply(
        self, conversation: Conversation, result, correlation_id: str | None
    ) -> Message:
        reply = Message(
            id=uuid7(),
            conversation_id=conversation.id,
            sender_type=SenderType.DIRA,
            sender_id=None,
            content=result.text,
            created_at=datetime.now(UTC),
            ai_request_id=UUID(result.ai_request_id),
            simulated=result.simulated,
        )
        await self._messages.add(reply)
        await self._outbox.add(
            ai_response_generated(
                message_id=reply.id,
                conversation_id=conversation.id,
                ai_request_id=reply.ai_request_id,
                simulated=result.simulated,
                organization_id=conversation.organization_id,
                occurred_at=reply.created_at,
                correlation_id=correlation_id,
            )
        )
        return reply

    async def _generate_dira_reply(
        self, conversation: Conversation, correlation_id: str | None
    ) -> Message | None:
        """Dira answers patient messages through the AI Gateway (ADR 0005:
        synchronous in the request while the provider is the instant fake).
        Dira being unavailable must never block the patient's message, so
        gateway failures are swallowed here; the gateway has already audited
        them in ai_requests."""
        llm_messages = await self._build_history(conversation)
        try:
            result = await self._gateway.complete(
                prompt_name="dira_reply",
                user_messages=llm_messages,
                organization_id=conversation.organization_id,
                correlation_id=correlation_id,
                tools=self._tools_for_turn(conversation, correlation_id, llm_messages),
            )
        except AppError:
            return None
        return await self._persist_dira_reply(conversation, result, correlation_id)

    async def stream_dira_reply(self, actor: User, conversation_id: UUID, correlation_id):
        """Streaming variant: yields tool, delta, and message events. The
        caller has already saved the patient's message."""
        conversation = await self._conversations.get_by_id(conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found")
        if actor.role is not Role.PATIENT or conversation.patient_id != actor.id:
            raise ForbiddenError("Only the conversation's patient talks with Dira")
        llm_messages = await self._build_history(conversation)
        result = None
        try:
            async for event in self._gateway.stream_reply(
                prompt_name="dira_reply",
                user_messages=llm_messages,
                organization_id=conversation.organization_id,
                correlation_id=correlation_id,
                tools=self._tools_for_turn(conversation, correlation_id, llm_messages),
            ):
                if event["type"] == "result":
                    result = event["result"]
                else:
                    yield event
        except AppError:
            yield {"type": "error", "detail": "Dira is unavailable right now."}
            return
        if result is None:
            yield {"type": "error", "detail": "Dira is unavailable right now."}
            return
        reply = await self._persist_dira_reply(conversation, result, correlation_id)
        yield {
            "type": "message",
            "message": {
                "id": str(reply.id),
                "conversation_id": str(reply.conversation_id),
                "sender_type": reply.sender_type.value,
                "sender_id": None,
                "content": reply.content,
                "created_at": reply.created_at.isoformat(),
                "simulated": reply.simulated,
            },
        }

    async def _therapist_assigned(self, actor: User, conversation: Conversation) -> bool:
        if actor.role is not Role.THERAPIST:
            return False
        return await self._assignments.is_assigned(actor.id, conversation.patient_id)
