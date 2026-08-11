"""FastAPI dependencies: db session, current user, and service wiring."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ai.gateway import AIGateway
from app.application.errors import UnauthorizedError
from app.application.use_cases.auth import AuthService
from app.application.use_cases.conversations import ConversationService
from app.application.use_cases.guardians import GuardianService
from app.application.use_cases.knowledge import KnowledgeService
from app.application.use_cases.ops import OpsService
from app.application.use_cases.referrals import ReferralService
from app.application.use_cases.reviews import ReviewService
from app.domain.entities import User
from app.infrastructure.ai.embeddings import create_embedding_provider
from app.infrastructure.ai.factory import create_provider
from app.infrastructure.repositories import (
    SqlAIRequestLog,
    SqlAIRequestQuery,
    SqlAuthSessionRepository,
    SqlCareAssignmentRepository,
    SqlChunkRepository,
    SqlConversationRepository,
    SqlDocumentRepository,
    SqlEventLogQuery,
    SqlEventOutbox,
    SqlGuardianRepository,
    SqlMessageRepository,
    SqlRagRetrievalRepository,
    SqlReferralRepository,
    SqlRiskRepository,
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
    )


TokenServiceDep = Annotated[JwtTokenService, Depends(get_token_service)]


def get_auth_service(
    session: SessionDep, settings: SettingsDep, tokens: TokenServiceDep
) -> AuthService:
    return AuthService(
        users=SqlUserRepository(session),
        sessions=SqlAuthSessionRepository(session),
        hasher=Argon2PasswordHasher(),
        tokens=tokens,
        access_ttl_seconds=settings.access_token_ttl_seconds,
        refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
    )


def get_ai_gateway(request: Request, settings: SettingsDep) -> AIGateway:
    return AIGateway(
        create_provider(settings.llm_provider),
        SqlAIRequestLog(request.app.state.session_factory),
        timeout_seconds=settings.ai_timeout_seconds,
    )


AIGatewayDep = Annotated[AIGateway, Depends(get_ai_gateway)]


def get_conversation_service(session: SessionDep, gateway: AIGatewayDep) -> ConversationService:
    return ConversationService(
        conversations=SqlConversationRepository(session),
        messages=SqlMessageRepository(session),
        assignments=SqlCareAssignmentRepository(session),
        outbox=SqlEventOutbox(session),
        gateway=gateway,
    )


def get_correlation_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


CorrelationIdDep = Annotated[str | None, Depends(get_correlation_id)]


def get_review_service(session: SessionDep) -> ReviewService:
    return ReviewService(
        workflows=SqlWorkflowRepository(session),
        risks=SqlRiskRepository(session),
        assignments=SqlCareAssignmentRepository(session),
        users=SqlUserRepository(session),
        messages=SqlMessageRepository(session),
        outbox=SqlEventOutbox(session),
    )


ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]


def get_ops_service(session: SessionDep) -> OpsService:
    return OpsService(
        workflows=SqlWorkflowRepository(session),
        ai_requests=SqlAIRequestQuery(session),
        events=SqlEventLogQuery(session),
    )


OpsServiceDep = Annotated[OpsService, Depends(get_ops_service)]


def get_knowledge_service(
    session: SessionDep, settings: SettingsDep, gateway: AIGatewayDep
) -> KnowledgeService:
    return KnowledgeService(
        documents=SqlDocumentRepository(session),
        chunks=SqlChunkRepository(session),
        retrievals=SqlRagRetrievalRepository(session),
        embedder=create_embedding_provider(settings.embedding_provider),
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
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
