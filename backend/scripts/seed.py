"""Seed demo data for local dev. Idempotent: safe to run repeatedly.

All people and organizations here are fictional. This is a portfolio
simulation, not a real healthcare product.

Run: uv run python -m scripts.seed
"""

import asyncio
from datetime import UTC, datetime

import structlog

from app.application.use_cases.knowledge import KnowledgeService
from app.domain.entities import CareAssignment, Organization, Role, User
from app.domain.ids import uuid7
from app.infrastructure.ai.embeddings import LocalLexicalEmbedding
from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.repositories import (
    SqlCareAssignmentRepository,
    SqlChunkRepository,
    SqlDocumentRepository,
    SqlGuardianRepository,
    SqlOrganizationRepository,
    SqlRagRetrievalRepository,
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
    ("guardian@demo.caremesh.org", Role.GUARDIAN, "Gale Guardian"),
    ("school@demo.caremesh.org", Role.SCHOOL_STAFF, "Sky Counselor"),
]

# Fictional resource documents for the knowledge library. Plain wellbeing
# information in a supportive register; nothing clinical.
DOCUMENTS = [
    (
        "Sleep and exam season",
        "sleep-exam-season",
        """Sleep gets harder exactly when it matters most. During exam season,
worry keeps the mind busy at night, and lost sleep then makes the worry
louder the next day. Breaking that loop starts small.

Try keeping a regular wind down time: screens away thirty minutes before
bed, and write tomorrow's three biggest tasks on paper so your head does
not have to hold them overnight. If you lie awake longer than twenty
minutes, get up, sit somewhere dim, and do something quiet until you feel
sleepy again.

One rough night before an exam is normal and your body can handle it.
If sleep has been hard for more than two weeks, tell your care team; that
is exactly what they are there for.""",
    ),
    (
        "What happens after a referral",
        "after-a-referral",
        """A referral simply means someone who cares about you asked the care
team to take a closer look. Nothing about it goes on any school record,
and it does not mean anything is wrong with you.

First, a member of the care team reads the referral, usually within a few
days. Then they reach out to you directly to set up a first conversation.
That first meeting is about getting to know you: what is going well, what
feels heavy, and what kind of support would actually help.

You can bring a parent or guardian if you want, or ask for them not to be
involved where the rules allow it. You can also change your mind about
support at any time. The care team works for you, not the other way
around.""",
    ),
    (
        "Grounding techniques for anxious moments",
        "grounding-techniques",
        """When anxiety spikes, your body sounds an alarm even when there is no
real danger. Grounding techniques help switch the alarm off by pointing
your attention at the present moment.

A simple one is five four three two one: name five things you can see,
four you can feel, three you can hear, two you can smell, and one you can
taste. Another is box breathing: breathe in for four counts, hold for
four, out for four, hold for four, and repeat a few rounds.

These are tools for the moment, not a fix for everything. If anxious
moments come often or get in the way of school or friends, bring it up
with Dira or your care team so you do not have to manage it alone.""",
    ),
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

        knowledge = KnowledgeService(
            documents=SqlDocumentRepository(session),
            chunks=SqlChunkRepository(session),
            retrievals=SqlRagRetrievalRepository(session),
            embedder=LocalLexicalEmbedding(),
            gateway=None,
        )
        for title, source_name, content in DOCUMENTS:
            _, chunk_count = await knowledge.ingest(
                created[Role.OPS_ADMIN], title, source_name, content
            )
            if chunk_count:
                log.info("seed_ingested_document", source=source_name, chunks=chunk_count)

        therapist, patient = created[Role.THERAPIST], created[Role.PATIENT]
        guardians = SqlGuardianRepository(session)
        if not await guardians.guardians_for_patient(patient.id):
            await guardians.add_link(
                organization_id=org.id,
                guardian_id=created[Role.GUARDIAN].id,
                patient_id=patient.id,
                now=now,
            )
            log.info("seed_created_guardian_link")
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
