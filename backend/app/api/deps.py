"""FastAPI dependencies: db session, current user, and service wiring."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import UnauthorizedError
from app.application.use_cases.auth import AuthService
from app.application.use_cases.conversations import ConversationService
from app.domain.entities import User
from app.infrastructure.repositories import (
    SqlAuthSessionRepository,
    SqlCareAssignmentRepository,
    SqlConversationRepository,
    SqlEventOutbox,
    SqlMessageRepository,
    SqlUserRepository,
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


def get_conversation_service(session: SessionDep) -> ConversationService:
    return ConversationService(
        conversations=SqlConversationRepository(session),
        messages=SqlMessageRepository(session),
        assignments=SqlCareAssignmentRepository(session),
        outbox=SqlEventOutbox(session),
    )


def get_correlation_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


CorrelationIdDep = Annotated[str | None, Depends(get_correlation_id)]


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
