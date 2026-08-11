from datetime import UTC, datetime

import pytest

from app.application.errors import UnauthorizedError
from app.domain.entities import Role, User
from app.domain.ids import uuid7
from app.infrastructure.security import Argon2PasswordHasher, JwtTokenService


def make_user() -> User:
    return User(
        id=uuid7(),
        organization_id=uuid7(),
        email="u@test",
        password_hash="x",
        role=Role.PATIENT,
        display_name="U",
        is_active=True,
        created_at=datetime.now(UTC),
    )


def make_service(access_ttl: int = 60) -> JwtTokenService:
    return JwtTokenService(
        secret="unit-test-secret",
        algorithm="HS256",
        access_ttl_seconds=access_ttl,
        refresh_ttl_seconds=3600,
    )


def test_password_hash_roundtrip():
    hasher = Argon2PasswordHasher()
    digest = hasher.hash("correct horse")
    assert hasher.verify(digest, "correct horse")
    assert not hasher.verify(digest, "wrong horse")
    assert not hasher.verify("not-a-hash", "anything")


def test_access_token_roundtrip():
    service = make_service()
    user = make_user()
    claims = service.decode(service.create_access_token(user), expected_type="access")
    assert claims["sub"] == str(user.id)
    assert claims["role"] == "patient"


def test_wrong_token_type_rejected():
    service = make_service()
    token = service.create_refresh_token(make_user(), uuid7())
    with pytest.raises(UnauthorizedError):
        service.decode(token, expected_type="access")


def test_expired_token_rejected():
    service = make_service(access_ttl=-10)
    token = service.create_access_token(make_user())
    with pytest.raises(UnauthorizedError):
        service.decode(token, expected_type="access")


def test_tampered_token_rejected():
    service = make_service()
    token = service.create_access_token(make_user())
    with pytest.raises(UnauthorizedError):
        service.decode(token[:-2] + "xx", expected_type="access")
