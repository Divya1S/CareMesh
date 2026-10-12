"""FastAPI dependencies: db session, current user, and service wiring."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ai.gateway import AIGateway
from app.application.errors import RateLimitedError, UnauthorizedError
from app.application.use_cases.appointments import AppointmentService
from app.application.use_cases.auth import AuthService
from app.application.use_cases.claims import ClaimsService
from app.application.use_cases.conversations import ConversationService
from app.application.use_cases.guardians import GuardianService
from app.application.use_cases.knowledge import KnowledgeService
from app.application.use_cases.ops import OpsService
from app.application.use_cases.referrals import ReferralService
from app.application.use_cases.reviews import ReviewService
from app.domain.entities import User
from app.infrastructure.ai.embeddings import EmbeddingProvider
from app.infrastructure.payer.fake_payer import FakePayerAdapter
from app.infrastructure.rate_limit import RedisRateLimiter
from app.infrastructure.repositories import (
    SqlAIRequestQuery,
    SqlAppointmentRepository,
    SqlAuditLog,
    SqlAuthSessionRepository,
    SqlCareAssignmentRepository,
    SqlChunkRepository,
    SqlClaimRepository,
    SqlConversationRepository,
    SqlDocumentRepository,
    SqlEventLogQuery,
    SqlEventOutbox,
    SqlGuardianRepository,
    SqlMessageRepository,
    SqlRagRetrievalRepository,
    SqlReferralRepository,
    SqlRiskRepository,
    SqlSessionRevoker,
    SqlUserRepository,
    SqlWorkflowRepository,
)
from app.infrastructure.security import Argon2PasswordHasher, JwtTokenService
from app.infrastructure.settings import Settings, get_settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_token_service(settings: SettingsDep) -> JwtTokenService:
    return JwtTokenService(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        access_ttl_seconds=settings.access_token_ttl_seconds,
        refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )


TokenServiceDep = Annotated[JwtTokenService, Depends(get_token_service)]


def get_audit_log(request: Request) -> SqlAuditLog:
    # Own pool: an audit write never waits on the request's connection.
    return SqlAuditLog(request.app.state.audit_session_factory)


AuditLogDep = Annotated[SqlAuditLog, Depends(get_audit_log)]


def get_auth_service(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    tokens: TokenServiceDep,
    audit: AuditLogDep,
) -> AuthService:
    return AuthService(
        users=SqlUserRepository(session),
        sessions=SqlAuthSessionRepository(session),
        hasher=Argon2PasswordHasher(),
        tokens=tokens,
        audit=audit,
        revoker=SqlSessionRevoker(request.app.state.audit_session_factory),
        access_ttl_seconds=settings.access_token_ttl_seconds,
        refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
    )


def get_ai_gateway(request: Request) -> AIGateway:
    """Built once in the lifespan (see main.configure_state)."""
    return request.app.state.gateway


def get_embedder(request: Request) -> EmbeddingProvider:
    return request.app.state.embedder


AIGatewayDep = Annotated[AIGateway, Depends(get_ai_gateway)]
EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedder)]


def get_conversation_service(
    session: SessionDep, gateway: AIGatewayDep, embedder: EmbedderDep
) -> ConversationService:
    return ConversationService(
        conversations=SqlConversationRepository(session),
        messages=SqlMessageRepository(session),
        assignments=SqlCareAssignmentRepository(session),
        outbox=SqlEventOutbox(session),
        gateway=gateway,
        knowledge=KnowledgeService(
            documents=SqlDocumentRepository(session),
            chunks=SqlChunkRepository(session),
            retrievals=SqlRagRetrievalRepository(session),
            embedder=embedder,
            gateway=None,
        ),
        appointments=SqlAppointmentRepository(session),
        workflows=SqlWorkflowRepository(session),
        release=session.commit,
    )


def get_appointment_service(session: SessionDep) -> AppointmentService:
    return AppointmentService(
        appointments=SqlAppointmentRepository(session),
        workflows=SqlWorkflowRepository(session),
        assignments=SqlCareAssignmentRepository(session),
    )


AppointmentServiceDep = Annotated[AppointmentService, Depends(get_appointment_service)]


def get_correlation_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


CorrelationIdDep = Annotated[str | None, Depends(get_correlation_id)]


def get_review_service(session: SessionDep, audit: AuditLogDep) -> ReviewService:
    return ReviewService(
        workflows=SqlWorkflowRepository(session),
        risks=SqlRiskRepository(session),
        assignments=SqlCareAssignmentRepository(session),
        users=SqlUserRepository(session),
        messages=SqlMessageRepository(session),
        outbox=SqlEventOutbox(session),
        audit=audit,
    )


ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]


def get_ops_service(session: SessionDep, audit: AuditLogDep) -> OpsService:
    return OpsService(
        workflows=SqlWorkflowRepository(session),
        ai_requests=SqlAIRequestQuery(session),
        events=SqlEventLogQuery(session),
        audit=audit,
    )


OpsServiceDep = Annotated[OpsService, Depends(get_ops_service)]


def get_knowledge_service(
    session: SessionDep, gateway: AIGatewayDep, embedder: EmbedderDep
) -> KnowledgeService:
    return KnowledgeService(
        documents=SqlDocumentRepository(session),
        chunks=SqlChunkRepository(session),
        retrievals=SqlRagRetrievalRepository(session),
        embedder=embedder,
        gateway=gateway,
    )


KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]


def get_referral_service(session: SessionDep) -> ReferralService:
    return ReferralService(
        referrals=SqlReferralRepository(session),
        workflows=SqlWorkflowRepository(session),
        users=SqlUserRepository(session),
        assignments=SqlCareAssignmentRepository(session),
        guardians=SqlGuardianRepository(session),
        outbox=SqlEventOutbox(session),
    )


ReferralServiceDep = Annotated[ReferralService, Depends(get_referral_service)]


def get_guardian_service(session: SessionDep) -> GuardianService:
    return GuardianService(
        guardians=SqlGuardianRepository(session),
        assignments=SqlCareAssignmentRepository(session),
        users=SqlUserRepository(session),
        outbox=SqlEventOutbox(session),
    )


GuardianServiceDep = Annotated[GuardianService, Depends(get_guardian_service)]


def get_claims_service(session: SessionDep, audit: AuditLogDep) -> ClaimsService:
    return ClaimsService(
        claims=SqlClaimRepository(session),
        workflows=SqlWorkflowRepository(session),
        assignments=SqlCareAssignmentRepository(session),
        adapter=FakePayerAdapter(),
        outbox=SqlEventOutbox(session),
        audit=audit,
    )


ClaimsServiceDep = Annotated[ClaimsService, Depends(get_claims_service)]


async def get_current_user(request: Request, session: SessionDep, tokens: TokenServiceDep) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedError("Missing bearer token")
    claims = tokens.decode(token, expected_type="access")
    user = await SqlUserRepository(session).get_by_id(UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedError("Account is not active")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_rate_limiter(request: Request) -> RedisRateLimiter:
    return RedisRateLimiter(request.app.state.redis)


RateLimiterDep = Annotated[RedisRateLimiter, Depends(get_rate_limiter)]


async def enforce_ai_rate_limit(
    user: CurrentUserDep, limiter: RateLimiterDep, settings: SettingsDep
) -> None:
    """Cost control on endpoints that reach the AI Gateway, per user. Fails
    open: a Redis outage must not stop a student from sending a message."""
    decision = await limiter.allow(
        f"ai:{user.id}", settings.ai_requests_per_minute, window_seconds=60, on_failure="open"
    )
    if not decision.allowed:
        raise RateLimitedError(
            "You are sending requests faster than the assistant can keep up. "
            "Take a short breather and try again.",
            retry_after_seconds=decision.retry_after_seconds,
        )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]


def client_address(request: Request, settings: Settings) -> str:
    """The address the login limiter buckets on. Behind a reverse proxy the
    socket peer is the proxy, so when TRUST_PROXY_HEADERS is on the first
    X-Forwarded-For entry is used instead. Off by default: trusting that
    header from the open internet lets a client pick its own bucket."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    return request.client.host if request.client else "unknown"
