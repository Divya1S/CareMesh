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


class EligibilityRequest(BaseModel):
    member_id: str = Field(min_length=3, max_length=100)


class EligibilityResponse(BaseModel):
    eligibility_check_id: UUID
    eligible: bool
    plan_name: str
    adapter: str
    # The external payer is a labeled simulation (fake-payer-1).
    simulated: bool


class ClaimSubmitRequest(BaseModel):
    patient_id: UUID
    description: str = Field(min_length=5, max_length=500)
    amount_cents: int = Field(gt=0, le=10_000_00)
    eligibility_check_id: UUID


class ClaimResponse(BaseModel):
    claim_id: UUID
    workflow_id: UUID
    patient_name: str
    description: str
    amount_cents: int
    member_id: str
    plan_name: str
    # Mirrors the workflow state machine exactly: submitted, approved,
    # denied, resubmitted.
    state: str
    denial_reason: str | None
    resubmit_note: str | None
    created_at: datetime


class ClaimDecideRequest(BaseModel):
    approve: bool
    denial_reason: str | None = Field(default=None, max_length=500)


class ClaimResubmitRequest(BaseModel):
    note: str = Field(min_length=5, max_length=500)


class RosterEntryResponse(BaseModel):
    patient_id: UUID
    name: str


class ReferralSubmitRequest(BaseModel):
    patient_id: UUID
    concern: str = Field(min_length=10, max_length=4000)
    consent_confirmed: bool


class ReferralResponse(BaseModel):
    referral_id: UUID
    workflow_id: UUID
    patient_id: UUID
    patient_name: str
    # Mirrors the workflow state machine names exactly: submitted,
    # accepted, declined.
    state: str
    created_at: datetime
    concern: str | None


class ReferralDecideRequest(BaseModel):
    accept: bool


class GuardianOverviewResponse(BaseModel):
    students: list[dict]
    updates: list[dict]
    notifications: list[dict]


class GuardianUpdateRequest(BaseModel):
    patient_id: UUID
    content: str = Field(min_length=5, max_length=4000)


class KnowledgeDocumentResponse(BaseModel):
    id: UUID
    title: str
    source_name: str
    version: int
    created_at: datetime


class DocumentIngestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    source_name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)


class DocumentIngestResponse(BaseModel):
    document: KnowledgeDocumentResponse
    chunk_count: int
    unchanged: bool


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class CitationResponse(BaseModel):
    chunk_id: UUID
    document_title: str
    document_version: int
    snippet: str
    score: float
    # Whether the answer actually cited this retrieved chunk.
    used: bool


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    simulated: bool | None
    model: str | None
    citations: list[CitationResponse]


class OpsWorkflowResponse(BaseModel):
    id: UUID
    workflow_type: str
    state: str
    subject_id: UUID
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime


class OpsTransitionResponse(BaseModel):
    from_state: str | None
    to_state: str
    actor: str
    reason: str
    occurred_at: datetime


class OpsWorkflowDetailResponse(BaseModel):
    workflow: OpsWorkflowResponse
    transitions: list[OpsTransitionResponse]


class OpsAIRequestResponse(BaseModel):
    id: UUID
    provider: str
    model: str
    prompt_name: str
    prompt_version: int
    status: str
    simulated: bool
    validation_ok: bool | None
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    correlation_id: str | None
    error_type: str | None
    created_at: datetime


class OpsAIRequestDetailResponse(OpsAIRequestResponse):
    request_messages: list[dict]
    response_text: str | None


class OpsEventResponse(BaseModel):
    id: UUID
    event_type: str
    schema_version: int
    occurred_at: datetime
    published_at: datetime | None
    correlation_id: str | None


class OpsDlqResponse(BaseModel):
    topic: str
    records: list[str]


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
