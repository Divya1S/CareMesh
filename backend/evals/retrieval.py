"""Retrieval quality suite v1: hit@k and MRR over the real pipeline.

Ingests the fixture corpus into an isolated throwaway organization in the
test database, runs each query through the same search and rerank code the
product uses, computes the metrics, and deletes everything it created.
The default embeddings are lexical (ADR 0006), so queries here validate the
pipeline with realistic lexical overlap; the same dataset reruns unchanged
when a semantic provider is switched on.
"""

import os
from datetime import UTC, datetime

from sqlalchemy import delete

from app.application.use_cases.knowledge import MIN_SCORE, RETRIEVE_K, rerank
from app.domain.entities import Organization, Role, User
from app.domain.ids import uuid7
from app.infrastructure.ai.embeddings import LocalLexicalEmbedding
from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.models import DocumentChunkRow, DocumentRow, OrganizationRow, UserRow
from app.infrastructure.repositories import (
    SqlChunkRepository,
    SqlDocumentRepository,
    SqlOrganizationRepository,
    SqlRagRetrievalRepository,
    SqlUserRepository,
)
from scripts.seed import DOCUMENTS as CORPUS  # the three fictional resource docs

DATASET_VERSION = "retrieval-v1"

EVAL_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://caremesh:caremesh_dev_password@localhost:5433/caremesh_test",
)

QUERIES = [
    {
        "id": "sleep-before-exam",
        "query": "how can I sleep better before my exam",
        "expected_source": "sleep-exam-season",
    },
    {
        "id": "after-referral",
        "query": "what happens after a referral to the care team",
        "expected_source": "after-a-referral",
    },
    {
        "id": "calming-anxiety",
        "query": "grounding techniques when I feel anxious",
        "expected_source": "grounding-techniques",
    },
    {
        "id": "off-domain",
        "query": "zebra quantum warp drive maintenance",
        "expected_source": None,  # must retrieve nothing above the threshold
    },
]


async def run_retrieval_suite() -> dict:
    from app.application.use_cases.knowledge import KnowledgeService

    engine = create_engine(EVAL_DB_URL)
    session_factory = create_session_factory(engine)
    embedder = LocalLexicalEmbedding()
    now = datetime.now(UTC)
    org = Organization(id=uuid7(), name=f"eval-{uuid7()}", created_at=now)
    ops = User(
        id=uuid7(),
        organization_id=org.id,
        email=f"{uuid7()}@eval.caremesh.org",
        password_hash="eval",
        role=Role.OPS_ADMIN,
        display_name="Eval Ops",
        is_active=True,
        created_at=now,
    )
    results = []
    try:
        async with session_factory() as session:
            await SqlOrganizationRepository(session).add(org)
            await session.flush()
            await SqlUserRepository(session).add(ops)
            await session.flush()
            service = KnowledgeService(
                documents=SqlDocumentRepository(session),
                chunks=SqlChunkRepository(session),
                retrievals=SqlRagRetrievalRepository(session),
                embedder=embedder,
                gateway=None,
            )
            source_by_doc: dict = {}
            for title, source_name, content in CORPUS:
                document, _ = await service.ingest(ops, title, source_name, content)
                source_by_doc[document.id] = source_name
            await session.commit()

            chunks = SqlChunkRepository(session)
            for case in QUERIES:
                embedding = embedder.embed([case["query"]])[0]
                candidates = await chunks.search(org.id, embedding, RETRIEVE_K)
                ranked = [c for c in rerank(case["query"], candidates) if c.score >= MIN_SCORE]
                retrieved_sources = [source_by_doc[c.chunk.document_id] for c in ranked]
                expected = case["expected_source"]
                if expected is None:
                    passed = len(ranked) == 0
                    rank = None
                else:
                    rank = (
                        retrieved_sources.index(expected) + 1
                        if expected in retrieved_sources
                        else None
                    )
                    passed = rank == 1
                results.append(
                    {
                        "id": case["id"],
                        "expected": expected,
                        "retrieved": retrieved_sources[:3],
                        "rank": rank,
                        "passed": passed,
                    }
                )
        return {
            "dataset_version": DATASET_VERSION,
            "embedding": embedder.name,
            "cases": results,
            "passed": sum(1 for r in results if r["passed"]),
            "total": len(results),
            "hit_at_1": _hit_rate(results, 1),
            "hit_at_3": _hit_rate(results, 3),
            "mrr": _mrr(results),
        }
    finally:
        # Remove everything this run created, then release the engine.
        async with session_factory() as session:
            await session.execute(
                delete(DocumentChunkRow).where(DocumentChunkRow.organization_id == org.id)
            )
            await session.execute(delete(DocumentRow).where(DocumentRow.organization_id == org.id))
            await session.execute(delete(UserRow).where(UserRow.id == ops.id))
            await session.execute(delete(OrganizationRow).where(OrganizationRow.id == org.id))
            await session.commit()
        await engine.dispose()


def _positives(results: list[dict]) -> list[dict]:
    return [r for r in results if r["expected"] is not None]


def _hit_rate(results: list[dict], k: int) -> float:
    positives = _positives(results)
    if not positives:
        return 0.0
    hits = sum(1 for r in positives if r["rank"] is not None and r["rank"] <= k)
    return round(hits / len(positives), 3)


def _mrr(results: list[dict]) -> float:
    positives = _positives(results)
    if not positives:
        return 0.0
    total = sum(1.0 / r["rank"] for r in positives if r["rank"] is not None)
    return round(total / len(positives), 3)
