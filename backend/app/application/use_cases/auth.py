"""Login and token refresh use cases."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.errors import UnauthorizedError
from app.application.ports import (
    AuthSessionRepository,
    PasswordHasher,
    TokenService,
    UserRepository,
)
from app.domain.entities import AuthSession, User
from app.domain.ids import uuid7


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_in: int


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        sessions: AuthSessionRepository,
        hasher: PasswordHasher,
        tokens: TokenService,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._hasher = hasher
        self._tokens = tokens
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self._users.get_by_email(email.strip().lower())
        # Verify against a constant dummy hash on unknown emails so response
        # timing does not reveal whether an account exists.
        if user is None:
            self._hasher.verify(_DUMMY_HASH, password)
            raise UnauthorizedError("Invalid email or password")
        if not self._hasher.verify(user.password_hash, password) or not user.is_active:
            raise UnauthorizedError("Invalid email or password")
        return await self._issue_pair(user)

    async def refresh(self, refresh_token: str) -> TokenPair:
        claims = self._tokens.decode(refresh_token, expected_type="refresh")
        session = await self._sessions.get_by_token_hash(self._tokens.token_hash(refresh_token))
        now = datetime.now(UTC)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise UnauthorizedError("Refresh token is no longer valid")
        user = await self._users.get_by_id(UUID(claims["sub"]))
        if user is None or not user.is_active:
            raise UnauthorizedError("Account is not active")
        # Rotation: each refresh token is single use.
        await self._sessions.revoke(session.id, revoked_at=now)
        return await self._issue_pair(user)

    async def _issue_pair(self, user: User) -> TokenPair:
        session_id = uuid7()
        refresh_token = self._tokens.create_refresh_token(user, session_id)
        now = datetime.now(UTC)
        await self._sessions.add(
            AuthSession(
                id=session_id,
                user_id=user.id,
                token_hash=self._tokens.token_hash(refresh_token),
                expires_at=now + timedelta(seconds=self._refresh_ttl),
                created_at=now,
            )
        )
        return TokenPair(
            access_token=self._tokens.create_access_token(user),
            refresh_token=refresh_token,
            access_expires_in=self._access_ttl,
        )


# A real Argon2 hash of a random throwaway string, used only to equalize timing.
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21lc2FsdA$"
    "kJQpUnGm2GJvbYyNn2sTEvxKq+d8p5t0XGpZM3n9NxY"
)
