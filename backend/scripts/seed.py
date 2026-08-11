"""Seed demo data for local dev. Idempotent: safe to run repeatedly.

All people and organizations here are fictional. This is a portfolio
simulation, not a real healthcare product.

Run: uv run python -m scripts.seed
"""

import asyncio
from datetime import UTC, datetime

import structlog

from app.domain.entities import CareAssignment, Organization, Role, User
from app.domain.ids import uuid7
from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.repositories import (
    SqlCareAssignmentRepository,
    SqlOrganizationRepository,
    SqlUserRepository,
)
from app.infrastructure.security import Argon2PasswordHasher
from app.infrastructure.settings import get_settings

# Demo credential for local dev only.
DEMO_PASSWORD = "caremesh-demo"

USERS = [
    ("student@demo.caremesh.org", Role.PATIENT, "Sam Student"),
    ("therapist@demo.caremesh.org", Role.THERAPIST, "Dr. Rivera"),
    ("ops@demo.caremesh.org", Role.OPS_ADMIN, "Olly Ops"),
]


async def seed() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    hasher = Argon2PasswordHasher()
    log = structlog.get_logger()

    async with session_factory() as session:
        orgs = SqlOrganizationRepository(session)
        users = SqlUserRepository(session)
        assignments = SqlCareAssignmentRepository(session)
        now = datetime.now(UTC)

        org = await orgs.get_by_name("Evergreen High (fictional)")
        if org is None:
            org = Organization(id=uuid7(), name="Evergreen High (fictional)", created_at=now)
            await orgs.add(org)
            log.info("seed_created_org")

        created: dict[Role, User] = {}
        for email, role, name in USERS:
            user = await users.get_by_email(email)
            if user is None:
                user = User(
                    id=uuid7(),
                    organization_id=org.id,
                    email=email,
                    password_hash=hasher.hash(DEMO_PASSWORD),
                    role=role,
                    display_name=name,
                    is_active=True,
                    created_at=now,
                )
                await users.add(user)
                log.info("seed_created_user", role=role.value)
            created[role] = user

        therapist, patient = created[Role.THERAPIST], created[Role.PATIENT]
        if not await assignments.is_assigned(therapist.id, patient.id):
            await assignments.add(
                CareAssignment(
                    id=uuid7(),
                    organization_id=org.id,
                    therapist_id=therapist.id,
                    patient_id=patient.id,
                    created_at=now,
                )
            )
            log.info("seed_created_assignment")

        await session.commit()

    await engine.dispose()
    log.info("seed_done", accounts=[email for email, _, _ in USERS], password=DEMO_PASSWORD)


if __name__ == "__main__":
    asyncio.run(seed())
