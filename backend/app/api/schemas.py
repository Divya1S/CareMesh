"""Request and response models at the API boundary."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.entities import Role, SenderType
from app.domain.risk import ReviewDecision, RiskCategory


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


class ReviewQueueItemResponse(BaseModel):
    workflow_id: UUID
    risk_signal_id: UUID
    patient_name: str
    message_content: str
    category: RiskCategory
    severity: int
    confidence: float
    evidence: str
    # AI provenance for the AIFrame in the workspace.
    model: str
    prompt_version: int
    simulated: bool
    created_at: datetime


class ReviewDecisionRequest(BaseModel):
    decision: ReviewDecision
    severity_override: int | None = Field(default=None, ge=0, le=3)
    note: str = Field(default="", max_length=2000)


class ReviewDecisionResponse(BaseModel):
    workflow_id: UUID
    state: str
    decision: ReviewDecision


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_type: SenderType
    sender_id: UUID | None
    content: str
    created_at: datetime
    # AI provenance: null for human senders. True means the reply came from
    # the fake provider and the UI must show the SIMULATED label.
    simulated: bool | None = None
