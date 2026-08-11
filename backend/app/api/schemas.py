"""Request and response models at the API boundary."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.entities import Role, SenderType


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    id: UUID
    email: str
    role: Role
    display_name: str
    organization_id: UUID


class ConversationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    id: UUID
    patient_id: UUID
    title: str
    created_at: datetime


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_type: SenderType
    sender_id: UUID | None
    content: str
    created_at: datetime
