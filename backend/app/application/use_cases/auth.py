"""Login and token refresh use cases."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.errors import UnauthorizedError
from app.application.ports import (
    AuditLog,
    AuthSessionRepository,
    PasswordHasher,
    SessionRevoker,
    TokenService,
    UserRepository,
)
from app.domain.entities import AuthSession, User
from app.domain.ids import uuid7


def mask_email(email: str) -> str:
    """st***@demo.example: enough to investigate, not enough to identify."""
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}" if domain else f"{local[:2]}***"


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
        audit: AuditLog,
        revoker: SessionRevoker,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._hasher = hasher
        self._tokens = tokens
        self._audit = audit
        self._revoker = revoker
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    async def login(self, email: str, password: str) -> TokenPair:
        normalized = email.strip().lower()
        user = await self._users.get_by_email(normalized)
        # Verify against a constant dummy hash on unknown emails so response
        # timing does not reveal whether an account exists.
        if user is None:
            self._hasher.verify(_DUMMY_HASH, password)
            await self._audit_failure(normalized)
            raise UnauthorizedError("Invalid email or password")
        if not self._hasher.verify(user.password_hash, password) or not user.is_active:
            await self._audit_failure(normalized)
            raise UnauthorizedError("Invalid email or password")
        await self._audit.record(
            action="login_success",
            organization_id=user.organization_id,
            actor_id=user.id,
        )
        return await self._issue_pair(user)

    async def _audit_failure(self, email: str) -> None:
        await self._audit.record(
            action="login_failed",
            organization_id=None,
            actor_id=None,
            detail={"email_masked": mask_email(email)},
        )

    async def refresh(self, refresh_token: str) -> TokenPair:
        """Rotation with reuse detection. Each refresh token is single use
        and belongs to the family its login started. Presenting a token
        that was already rotated means either a stolen token or a client
        bug; either way every token in the family is revoked, so a thief
        who refreshed first loses access as soon as the real client tries."""
        claims = self._tokens.decode(refresh_token, expected_type="refresh")
        session = await self._sessions.get_by_token_hash(self._tokens.token_hash(refresh_token))
        now = datetime.now(UTC)
        if session is None:
            raise UnauthorizedError("Refresh token is no longer valid")
        if session.revoked_at is not None:
            await self._revoke_family_for_reuse(session, now)
            raise UnauthorizedError("Refresh token was already used; sign in again")
        if session.expires_at <= now:
            raise UnauthorizedError("Refresh token has expired")
        user = await self._users.get_by_id(UUID(claims["sub"]))
        if user is None or not user.is_active:
            raise UnauthorizedError("Account is not active")
        # Conditional revoke: of two concurrent uses exactly one wins. The
        # loser is treated as reuse, because a legitimate client never
        # presents the same token twice.
        if not await self._sessions.revoke_if_active(session.id, revoked_at=now):
            await self._revoke_family_for_reuse(session, now)
            raise UnauthorizedError("Refresh token was already used; sign in again")
        return await self._issue_pair(user, family_id=session.family_id)

    async def _revoke_family_for_reuse(self, session: AuthSession, now: datetime) -> None:
        revoked = await self._revoker.revoke_family(session.family_id, revoked_at=now)
        await self._audit.record(
            action="refresh_token_reuse",
            organization_id=None,
            actor_id=session.user_id,
            resource_type="auth_session_family",
            resource_id=session.family_id,
            detail={"sessions_revoked": revoked},
        )

    async def _issue_pair(self, user: User, family_id: UUID | None = None) -> TokenPair:
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
                # A login starts a new family; a refresh stays in its own.
                family_id=family_id or session_id,
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
