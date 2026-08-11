"""Domain entities. Plain dataclasses, zero framework imports."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    PATIENT = "patient"
    GUARDIAN = "guardian"
    THERAPIST = "therapist"
    SCHOOL_STAFF = "school_staff"
    PAYER_STAFF = "payer_staff"
    OPS_ADMIN = "ops_admin"


class SenderType(StrEnum):
    PATIENT = "patient"
    DIRA = "dira"
    CLINICIAN = "clinician"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Organization:
    id: UUID
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    organization_id: UUID
    email: str
    password_hash: str
    role: Role
    display_name: str
    is_active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuthSession:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    organization_id: UUID
    patient_id: UUID
    title: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Message:
    id: UUID
    conversation_id: UUID
    sender_type: SenderType
    # None for dira and system senders, a user id otherwise.
    sender_id: UUID | None
    content: str
    created_at: datetime
    # AI provenance: set only on dira messages. The simulated flag must
    # survive to the UI; it is never dropped.
    ai_request_id: UUID | None = None
    simulated: bool | None = None


@dataclass(frozen=True, slots=True)
class CareAssignment:
    id: UUID
    organization_id: UUID
    therapist_id: UUID
    patient_id: UUID
    created_at: datetime
