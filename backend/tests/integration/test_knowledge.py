"""The knowledge platform end to end: ingestion with versioning, tenant
scoped retrieval over pgvector, and grounded answers with citations."""

import pytest
from sqlalchemy import select

from app.infrastructure.models import DocumentChunkRow, DocumentRow, RagRetrievalRow

pytestmark = pytest.mark.integration

SLEEP_DOC = {
    "title": "Sleep and exam season",
    "source_name": "sleep-exam-season",
    "content": (
        "Sleep gets harder exactly when it matters most. During exam season, "
        "worry keeps the mind busy at night, and lost sleep makes the worry "
        "louder the next day.\n\nTry keeping a regular wind down time, with "
        "screens away thirty minutes before bed. Write tomorrow's three "
        "biggest tasks on paper so your head does not have to hold them "
        "overnight while you rest."
    ),
}


async def ingest(client, headers, doc=SLEEP_DOC):
    response = await client.post("/api/v1/knowledge/documents", json=doc, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_only_ops_can_ingest(client, seeded, auth_header):
    for email in ("patient@a.caremesh.org", "therapist@a.caremesh.org"):
        headers = await auth_header(email)
        response = await client.post("/api/v1/knowledge/documents", json=SLEEP_DOC, headers=headers)
        assert response.status_code == 403


async def test_ingest_chunks_and_embeds(client, app, seeded, auth_header):
    ops = await auth_header("ops@a.caremesh.org")
    body = await ingest(client, ops)
    assert body["document"]["version"] == 1
    assert body["chunk_count"] >= 1
    async with app.state.session_factory() as session:
        chunks = (await session.scalars(select(DocumentChunkRow))).all()
    assert len(chunks) == body["chunk_count"]
    assert all(chunk.embedding is not None for chunk in chunks)


async def test_reingest_same_content_is_idempotent(client, seeded, auth_header):
    ops = await auth_header("ops@a.caremesh.org")
    await ingest(client, ops)
    again = await ingest(client, ops)
    assert again["unchanged"] is True
    assert again["document"]["version"] == 1


async def test_changed_content_supersedes_previous_version(client, app, seeded, auth_header):
    ops = await auth_header("ops@a.caremesh.org")
    await ingest(client, ops)
    updated = dict(SLEEP_DOC, content=SLEEP_DOC["content"] + "\n\nA brand new final paragraph.")
    body = await ingest(client, ops, updated)
    assert body["document"]["version"] == 2

    async with app.state.session_factory() as session:
        docs = (await session.scalars(select(DocumentRow).order_by(DocumentRow.version))).all()
    assert [d.status.value for d in docs] == ["superseded", "ready"]

    # Listing shows only the current version.
    listed = (await client.get("/api/v1/knowledge/documents", headers=ops)).json()
    assert len(listed) == 1 and listed[0]["version"] == 2


async def test_ask_returns_grounded_cited_simulated_answer(client, app, seeded, auth_header):
    ops = await auth_header("ops@a.caremesh.org")
    await ingest(client, ops)

    student = await auth_header("patient@a.caremesh.org")
    response = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "how can I sleep better before my exam"},
        headers=student,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["simulated"] is True
    assert "sleep" in body["answer"].lower()
    assert body["citations"], "grounded answers must carry citations"
    assert any(c["used"] for c in body["citations"])
    assert body["citations"][0]["document_title"] == SLEEP_DOC["title"]

    async with app.state.session_factory() as session:
        trail = (await session.scalars(select(RagRetrievalRow))).all()
    assert len(trail) == 1
    assert trail[0].ai_request_id is not None
    assert trail[0].retrieved[0]["chunk_id"]


async def test_ask_with_no_relevant_sources_declines_honestly(client, app, seeded, auth_header):
    student = await auth_header("patient@a.caremesh.org")
    response = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "zebra quantum warp drive"},
        headers=student,
    )
    body = response.json()
    assert body["grounded"] is False
    assert body["citations"] == []
    assert body["simulated"] is None, "no AI call happens without sources"
    async with app.state.session_factory() as session:
        trail = (await session.scalars(select(RagRetrievalRow))).all()
    assert len(trail) == 1 and trail[0].retrieved == []


async def test_retrieval_is_tenant_scoped(client, seeded, auth_header):
    ops = await auth_header("ops@a.caremesh.org")
    await ingest(client, ops)

    other_patient = await auth_header("patient@b.caremesh.org")
    response = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "how can I sleep better before my exam"},
        headers=other_patient,
    )
    body = response.json()
    assert body["grounded"] is False, "org B must not retrieve org A documents"
    assert body["citations"] == []
