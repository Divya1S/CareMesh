"""Password hashing and JWT token services."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.application.errors import UnauthorizedError
from app.domain.entities import User


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._hasher = Argon2Hasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


class JwtTokenService:
    def __init__(
        self,
        secret: str,
        algorithm: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
    ) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    def create_access_token(self, user: User) -> str:
        return self._encode(
            {
                "sub": str(user.id),
                "org": str(user.organization_id),
                "role": user.role.value,
                "type": "access",
            },
            ttl_seconds=self._access_ttl,
        )

    def create_refresh_token(self, user: User, session_id: UUID) -> str:
        return self._encode(
            {"sub": str(user.id), "sid": str(session_id), "type": "refresh"},
            ttl_seconds=self._refresh_ttl,
        )

    def decode(self, token: str, expected_type: str) -> dict:
        try:
            claims = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("Invalid or expired token") from exc
        if claims.get("type") != expected_type:
            raise UnauthorizedError("Wrong token type")
        return claims

    def token_hash(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _encode(self, claims: dict, ttl_seconds: int) -> str:
        now = datetime.now(UTC)
        payload = {**claims, "iat": now, "exp": now + timedelta(seconds=ttl_seconds)}
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)
