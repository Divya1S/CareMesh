"""Shared fixtures. API tests run against the caremesh_test database in the
dockerized Postgres, with the schema applied through the real Alembic migrations."""

import os
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.domain.entities import CareAssignment, Organization, Role, User
from app.domain.ids import uuid7
from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.repositories import (
    SqlCareAssignmentRepository,
    SqlOrganizationRepository,
    SqlUserRepository,
)
from app.infrastructure.security import Argon2PasswordHasher

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://caremesh:caremesh_dev_password@localhost:5433/caremesh_test",
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")

# The suite logs in with the same few emails dozens of times per minute;
# the real brute force limit would trip constantly. The lockout test builds
# its own limiter state instead.
os.environ.setdefault("LOGIN_ATTEMPTS_PER_MINUTE", "100000")
from app.infrastructure.settings import get_settings  # noqa: E402

get_settings.cache_clear()

TEST_PASSWORD = "test-password-1"
# Hashed once at import time because Argon2 is deliberately slow.
_HASHER = Argon2PasswordHasher()
_PASSWORD_HASH = _HASHER.hash(TEST_PASSWORD)


@pytest.fixture(scope="session")
def migrated() -> None:
    from alembic import command
    from alembic.config import Config

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DB_URL
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
async def app(migrated):
    from redis.asyncio import Redis

    from app.main import create_app

    application = create_app()
    engine = create_engine(TEST_DB_URL)
    application.state.engine = engine
    application.state.session_factory = create_session_factory(engine)
    application.state.redis = Redis.from_url(TEST_REDIS_URL)
    yield application
    await application.state.redis.aclose()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE organizations, users, auth_sessions, conversations, "
                "messages, care_assignments, domain_event_log, processed_events, "
                "ai_requests, risk_signals, risk_reviews, workflow_instances, "
                "workflow_transitions, documents, document_chunks, rag_retrievals, "
                "referrals, guardian_links, guardian_updates, claims, eligibility_checks, "
                "guardian_notifications, audit_logs CASCADE"
            )
        )
    await engine.dispose()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _user(org_id, email: str, role: Role, name: str) -> User:
    return User(
        id=uuid7(),
        organization_id=org_id,
        email=email,
        password_hash=_PASSWORD_HASH,
        role=role,
        display_name=name,
        is_active=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
async def seeded(app) -> dict:
    """Two tenants. In org A: a patient, a second patient, an assigned therapist,
    an unassigned therapist, and an ops admin. In org B: one patient."""
    now = datetime.now(UTC)
    org_a = Organization(id=uuid7(), name="Test Org A", created_at=now)
    org_b = Organization(id=uuid7(), name="Test Org B", created_at=now)
    data = {
        "org_a": org_a,
        "org_b": org_b,
        "patient": _user(org_a.id, "patient@a.caremesh.org", Role.PATIENT, "Pat A"),
        "patient2": _user(org_a.id, "patient2@a.caremesh.org", Role.PATIENT, "Pia A"),
        "therapist": _user(org_a.id, "therapist@a.caremesh.org", Role.THERAPIST, "Thea A"),
        "therapist2": _user(org_a.id, "therapist2@a.caremesh.org", Role.THERAPIST, "Theo A"),
        "ops": _user(org_a.id, "ops@a.caremesh.org", Role.OPS_ADMIN, "Otto A"),
        "patient_b": _user(org_b.id, "patient@b.caremesh.org", Role.PATIENT, "Pam B"),
    }
    async with app.state.session_factory() as session:
        orgs = SqlOrganizationRepository(session)
        users = SqlUserRepository(session)
        assignments = SqlCareAssignmentRepository(session)
        await orgs.add(org_a)
        await orgs.add(org_b)
        # Flush per dependency level; without relationships SQLAlchemy will not
        # order these inserts for the foreign keys on its own.
        await session.flush()
        for key in ("patient", "patient2", "therapist", "therapist2", "ops", "patient_b"):
            await users.add(data[key])
        await session.flush()
        await assignments.add(
            CareAssignment(
                id=uuid7(),
                organization_id=org_a.id,
                therapist_id=data["therapist"].id,
                patient_id=data["patient"].id,
                created_at=now,
            )
        )
        await session.commit()
    return data


@pytest.fixture
def login(client):
    async def _login(email: str, password: str = TEST_PASSWORD) -> dict:
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _login


@pytest.fixture
def auth_header(login):
    async def _auth_header(email: str) -> dict:
        tokens = await login(email)
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    return _auth_header
