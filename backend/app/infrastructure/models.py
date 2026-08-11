"""SQLAlchemy ORM models. Mapped to and from domain entities by the repositories."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.entities import Role, SenderType


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False)


class OrganizationRow(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created_at()


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = _uuid_pk()
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()


class AuthSessionRow(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationRow(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_org_patient_created",
            "organization_id",
            "patient_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[UUID] = _uuid_pk()
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    sender_type: Mapped[SenderType] = mapped_column(
        Enum(SenderType, name="sender_type"), nullable=False
    )
    sender_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class DomainEventLogRow(Base):
    """Transactional outbox (ADR 0003). Append only; rows are never deleted."""

    __tablename__ = "domain_event_log"
    __table_args__ = (
        Index(
            "ix_domain_event_log_unpublished",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[int] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessedEventRow(Base):
    """Consumer idempotency ledger: at least once delivery, exactly once effect."""

    __tablename__ = "processed_events"

    consumer_group: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CareAssignmentRow(Base):
    __tablename__ = "care_assignments"
    __table_args__ = (
        UniqueConstraint("therapist_id", "patient_id", name="uq_care_assignment_pair"),
    )

    id: Mapped[UUID] = _uuid_pk()
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    therapist_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()
