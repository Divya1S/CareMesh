"""Ports the application layer depends on. Infrastructure implements them."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    AuthSession,
    CareAssignment,
    Conversation,
    Message,
    Organization,
    User,
)
from app.domain.events import DomainEvent


class UserRepository(Protocol):
    async def get_by_email(self, email: str) -> User | None: ...
    async def get_by_id(self, user_id: UUID) -> User | None: ...
    async def add(self, user: User) -> None: ...


class OrganizationRepository(Protocol):
    async def get_by_id(self, org_id: UUID) -> Organization | None: ...
    async def get_by_name(self, name: str) -> Organization | None: ...
    async def add(self, org: Organization) -> None: ...


class AuthSessionRepository(Protocol):
    async def add(self, session: AuthSession) -> None: ...
    async def get_by_token_hash(self, token_hash: str) -> AuthSession | None: ...
    async def revoke(self, session_id: UUID, revoked_at: datetime) -> None: ...


class ConversationRepository(Protocol):
    async def add(self, conversation: Conversation) -> None: ...
    async def get_by_id(self, conversation_id: UUID) -> Conversation | None: ...
    async def list_for_patient(
        self, organization_id: UUID, patient_id: UUID, limit: int, offset: int
    ) -> list[Conversation]: ...
    async def list_for_patients(
        self, organization_id: UUID, patient_ids: list[UUID], limit: int, offset: int
    ) -> list[Conversation]: ...


class MessageRepository(Protocol):
    async def add(self, message: Message) -> None: ...
    async def list_for_conversation(
        self, conversation_id: UUID, limit: int, offset: int
    ) -> list[Message]: ...


class CareAssignmentRepository(Protocol):
    async def add(self, assignment: CareAssignment) -> None: ...
    async def is_assigned(self, therapist_id: UUID, patient_id: UUID) -> bool: ...
    async def patient_ids_for_therapist(
        self, organization_id: UUID, therapist_id: UUID
    ) -> list[UUID]: ...


class AuditLog(Protocol):
    """Records sensitive actions. Implementations write in their own session
    so an audit entry survives the caller's rollback."""

    async def record(
        self,
        *,
        action: str,
        organization_id: UUID | None,
        actor_id: UUID | None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        detail: dict | None = None,
    ) -> None: ...


class EventOutbox(Protocol):
    """Writes domain events in the caller's transaction (ADR 0003)."""

    async def add(self, event: DomainEvent) -> None: ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, password_hash: str, password: str) -> bool: ...


class TokenService(Protocol):
    def create_access_token(self, user: User) -> str: ...
    def create_refresh_token(self, user: User, session_id: UUID) -> str: ...
    def decode(self, token: str, expected_type: str) -> dict: ...
    def token_hash(self, token: str) -> str: ...
