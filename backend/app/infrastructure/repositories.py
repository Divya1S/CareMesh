"""Repository implementations over SQLAlchemy, mapping rows to domain entities."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ai.types import AIRequestLogEntry
from app.domain.entities import (
    AuthSession,
    CareAssignment,
    Conversation,
    Message,
    Organization,
    User,
)
from app.domain.events import DomainEvent
from app.infrastructure.models import (
    AIRequestRow,
    AuthSessionRow,
    CareAssignmentRow,
    ConversationRow,
    DomainEventLogRow,
    MessageRow,
    OrganizationRow,
    UserRow,
)


def _user(row: UserRow) -> User:
    return User(
        id=row.id,
        organization_id=row.organization_id,
        email=row.email,
        password_hash=row.password_hash,
        role=row.role,
        display_name=row.display_name,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def _conversation(row: ConversationRow) -> Conversation:
    return Conversation(
        id=row.id,
        organization_id=row.organization_id,
        patient_id=row.patient_id,
        title=row.title,
        created_at=row.created_at,
    )


def _message(row: MessageRow) -> Message:
    return Message(
        id=row.id,
        conversation_id=row.conversation_id,
        sender_type=row.sender_type,
        sender_id=row.sender_id,
        content=row.content,
        created_at=row.created_at,
        ai_request_id=row.ai_request_id,
        simulated=row.simulated,
    )


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        row = await self._session.scalar(select(UserRow).where(UserRow.email == email))
        return _user(row) if row else None

    async def get_by_id(self, user_id: UUID) -> User | None:
        row = await self._session.get(UserRow, user_id)
        return _user(row) if row else None

    async def add(self, user: User) -> None:
        self._session.add(
            UserRow(
                id=user.id,
                organization_id=user.organization_id,
                email=user.email,
                password_hash=user.password_hash,
                role=user.role,
                display_name=user.display_name,
                is_active=user.is_active,
                created_at=user.created_at,
            )
        )


class SqlOrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, org_id: UUID) -> Organization | None:
        row = await self._session.get(OrganizationRow, org_id)
        return Organization(id=row.id, name=row.name, created_at=row.created_at) if row else None

    async def get_by_name(self, name: str) -> Organization | None:
        row = await self._session.scalar(
            select(OrganizationRow).where(OrganizationRow.name == name)
        )
        return Organization(id=row.id, name=row.name, created_at=row.created_at) if row else None

    async def add(self, org: Organization) -> None:
        self._session.add(OrganizationRow(id=org.id, name=org.name, created_at=org.created_at))


class SqlAuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, auth_session: AuthSession) -> None:
        self._session.add(
            AuthSessionRow(
                id=auth_session.id,
                user_id=auth_session.user_id,
                token_hash=auth_session.token_hash,
                expires_at=auth_session.expires_at,
                created_at=auth_session.created_at,
                revoked_at=auth_session.revoked_at,
            )
        )

    async def get_by_token_hash(self, token_hash: str) -> AuthSession | None:
        row = await self._session.scalar(
            select(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash)
        )
        if row is None:
            return None
        return AuthSession(
            id=row.id,
            user_id=row.user_id,
            token_hash=row.token_hash,
            expires_at=row.expires_at,
            created_at=row.created_at,
            revoked_at=row.revoked_at,
        )

    async def revoke(self, session_id: UUID, revoked_at: datetime) -> None:
        await self._session.execute(
            update(AuthSessionRow)
            .where(AuthSessionRow.id == session_id)
            .values(revoked_at=revoked_at)
        )


class SqlConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, conversation: Conversation) -> None:
        self._session.add(
            ConversationRow(
                id=conversation.id,
                organization_id=conversation.organization_id,
                patient_id=conversation.patient_id,
                title=conversation.title,
                created_at=conversation.created_at,
            )
        )

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        row = await self._session.get(ConversationRow, conversation_id)
        return _conversation(row) if row else None

    async def list_for_patient(
        self, organization_id: UUID, patient_id: UUID, limit: int, offset: int
    ) -> list[Conversation]:
        rows = await self._session.scalars(
            select(ConversationRow)
            .where(
                ConversationRow.organization_id == organization_id,
                ConversationRow.patient_id == patient_id,
            )
            .order_by(ConversationRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_conversation(r) for r in rows]

    async def list_for_patients(
        self, organization_id: UUID, patient_ids: list[UUID], limit: int, offset: int
    ) -> list[Conversation]:
        rows = await self._session.scalars(
            select(ConversationRow)
            .where(
                ConversationRow.organization_id == organization_id,
                ConversationRow.patient_id.in_(patient_ids),
            )
            .order_by(ConversationRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_conversation(r) for r in rows]


class SqlMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: Message) -> None:
        self._session.add(
            MessageRow(
                id=message.id,
                conversation_id=message.conversation_id,
                sender_type=message.sender_type,
                sender_id=message.sender_id,
                content=message.content,
                created_at=message.created_at,
                ai_request_id=message.ai_request_id,
                simulated=message.simulated,
            )
        )

    async def list_for_conversation(
        self, conversation_id: UUID, limit: int, offset: int
    ) -> list[Message]:
        rows = await self._session.scalars(
            select(MessageRow)
            .where(MessageRow.conversation_id == conversation_id)
            .order_by(MessageRow.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return [_message(r) for r in rows]


class SqlEventOutbox:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: DomainEvent) -> None:
        self._session.add(
            DomainEventLogRow(
                id=event.event_id,
                event_type=event.event_type,
                schema_version=event.schema_version,
                occurred_at=event.occurred_at,
                organization_id=event.organization_id,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                payload=event.payload,
                published_at=None,
            )
        )


class SqlAIRequestLog:
    def __init__(self, session_factory) -> None:
        # Own session per write: the log entry must survive even when the
        # calling transaction rolls back (failures are exactly what we audit).
        self._session_factory = session_factory

    async def add(self, entry: AIRequestLogEntry) -> None:
        async with self._session_factory() as session:
            session.add(
                AIRequestRow(
                    id=UUID(entry.id),
                    organization_id=UUID(entry.organization_id),
                    provider=entry.provider,
                    model=entry.model,
                    prompt_name=entry.prompt_name,
                    prompt_version=entry.prompt_version,
                    status=entry.status,
                    simulated=entry.simulated,
                    validation_ok=entry.validation_ok,
                    latency_ms=entry.latency_ms,
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    cost_usd=entry.cost_usd,
                    correlation_id=entry.correlation_id,
                    error_type=entry.error_type,
                    request_messages=entry.request_messages,
                    response_text=entry.response_text,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()


class SqlCareAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, assignment: CareAssignment) -> None:
        self._session.add(
            CareAssignmentRow(
                id=assignment.id,
                organization_id=assignment.organization_id,
                therapist_id=assignment.therapist_id,
                patient_id=assignment.patient_id,
                created_at=assignment.created_at,
            )
        )

    async def is_assigned(self, therapist_id: UUID, patient_id: UUID) -> bool:
        row = await self._session.scalar(
            select(CareAssignmentRow.id).where(
                CareAssignmentRow.therapist_id == therapist_id,
                CareAssignmentRow.patient_id == patient_id,
            )
        )
        return row is not None

    async def patient_ids_for_therapist(
        self, organization_id: UUID, therapist_id: UUID
    ) -> list[UUID]:
        rows = await self._session.scalars(
            select(CareAssignmentRow.patient_id).where(
                CareAssignmentRow.organization_id == organization_id,
                CareAssignmentRow.therapist_id == therapist_id,
            )
        )
        return list(rows)
