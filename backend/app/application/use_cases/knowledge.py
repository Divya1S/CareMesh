"""The knowledge platform: real ingestion, real retrieval, grounded answers.

Retrieval is genuine similarity search over chunked, versioned documents in
pgvector, tenant scoped. Generation goes through the gateway (simulated and
labeled on the fake provider). Every question stores its retrieval trail in
rag_retrievals: what was fetched, what was cited. No fake RAG.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.application.ai.gateway import AIGateway
from app.application.ai.types import LLMMessage
from app.application.errors import DomainValidationError, ForbiddenError
from app.domain.entities import Role, User
from app.domain.ids import uuid7
from app.domain.knowledge import (
    Document,
    DocumentChunk,
    DocumentStatus,
    RetrievedChunk,
    chunk_text,
    normalize_text,
)

RETRIEVE_K = 6
ANSWER_WITH_TOP = 3
MIN_SCORE = 0.05

_WORD = re.compile(r"[a-z0-9']+")


class KnowledgeAnswerDraft(BaseModel):
    """What the knowledge_answer prompt must return."""

    answer: str = Field(max_length=2000)
    cited_chunk_ids: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Citation:
    chunk_id: UUID
    document_title: str
    document_version: int
    snippet: str
    score: float
    used: bool


@dataclass(frozen=True, slots=True)
class KnowledgeAnswer:
    answer: str
    grounded: bool
    simulated: bool | None
    model: str | None
    citations: list[Citation]


def _keyword_overlap(question: str, content: str) -> float:
    q = set(_WORD.findall(question.lower()))
    c = set(_WORD.findall(content.lower()))
    if not q or not c:
        return 0.0
    return len(q & c) / len(q | c)


def rerank(question: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Second stage: blend vector similarity with direct keyword overlap."""

    def final_score(item: RetrievedChunk) -> float:
        return 0.7 * item.score + 0.3 * _keyword_overlap(question, item.chunk.content)

    rescored = [
        RetrievedChunk(
            chunk=item.chunk,
            document_title=item.document_title,
            document_version=item.document_version,
            score=round(final_score(item), 4),
        )
        for item in candidates
    ]
    return sorted(rescored, key=lambda item: item.score, reverse=True)


class KnowledgeService:
    def __init__(self, documents, chunks, retrievals, embedder, gateway: AIGateway | None) -> None:
        self._documents = documents
        self._chunks = chunks
        self._retrievals = retrievals
        self._embedder = embedder
        self._gateway = gateway

    async def ingest(
        self, actor: User, title: str, source_name: str, content: str
    ) -> tuple[Document, int]:
        if actor.role is not Role.OPS_ADMIN:
            raise ForbiddenError("Only operations admins ingest documents")
        normalized = normalize_text(content)
        if len(normalized) < 50:
            raise DomainValidationError("Document content is too short to ingest")
        sha = hashlib.sha256(normalized.encode()).hexdigest()

        latest = await self._documents.latest_for_source(actor.organization_id, source_name)
        if latest and latest.content_sha256 == sha and latest.status == DocumentStatus.READY:
            return latest, 0  # unchanged content: ingestion is idempotent

        now = datetime.now(UTC)
        document = Document(
            id=uuid7(),
            organization_id=actor.organization_id,
            title=title.strip(),
            source_name=source_name.strip(),
            version=(latest.version + 1) if latest else 1,
            status=DocumentStatus.INGESTING,
            content_sha256=sha,
            created_at=now,
        )
        await self._documents.add(document)

        pieces = chunk_text(normalized)
        embeddings = self._embedder.embed(pieces)
        for index, (piece, embedding) in enumerate(zip(pieces, embeddings, strict=True)):
            await self._chunks.add(
                DocumentChunk(
                    id=uuid7(),
                    document_id=document.id,
                    organization_id=actor.organization_id,
                    chunk_index=index,
                    content=piece,
                    created_at=now,
                ),
                embedding,
            )
        await self._documents.set_status(document.id, DocumentStatus.READY)
        if latest and latest.status == DocumentStatus.READY:
            await self._documents.set_status(latest.id, DocumentStatus.SUPERSEDED)
        return document, len(pieces)

    async def list_documents(self, actor: User) -> list[Document]:
        return await self._documents.list_ready_for_org(actor.organization_id)

    async def retrieve(self, organization_id, question: str) -> list[RetrievedChunk]:
        """Tenant scoped retrieval with rerank, shared by ask and by Dira's
        search_resources tool."""
        query_embedding = self._embedder.embed([question])[0]
        candidates = await self._chunks.search(organization_id, query_embedding, RETRIEVE_K)
        ranked = [c for c in rerank(question, candidates) if c.score >= MIN_SCORE]
        return ranked[:ANSWER_WITH_TOP]

    async def ask(self, actor: User, question: str, correlation_id: str | None) -> KnowledgeAnswer:
        if self._gateway is None:
            raise RuntimeError("KnowledgeService was built without a gateway")
        top = await self.retrieve(actor.organization_id, question)
        now = datetime.now(UTC)

        if not top:
            await self._store_retrieval(actor, question, None, [], now)
            return KnowledgeAnswer(
                answer=(
                    "I could not find anything about that in the resource "
                    "library, so I would rather not guess. Your care team is "
                    "the right place for this question."
                ),
                grounded=False,
                simulated=None,
                model=None,
                citations=[],
            )

        context = "\n\n".join(
            f"SOURCE {i + 1} [id={item.chunk.id}] {item.document_title} "
            f"v{item.document_version}:\n{item.chunk.content}"
            for i, item in enumerate(top)
        )
        result = await self._gateway.complete(
            prompt_name="knowledge_answer",
            user_messages=[LLMMessage("user", f"QUESTION: {question}\n\nSOURCES:\n{context}")],
            organization_id=actor.organization_id,
            correlation_id=correlation_id,
            response_schema=KnowledgeAnswerDraft,
        )
        draft: KnowledgeAnswerDraft = result.structured
        cited = set(draft.cited_chunk_ids)
        citations = [
            Citation(
                chunk_id=item.chunk.id,
                document_title=item.document_title,
                document_version=item.document_version,
                snippet=item.chunk.content[:200],
                score=item.score,
                used=str(item.chunk.id) in cited,
            )
            for item in top
        ]
        await self._store_retrieval(actor, question, UUID(result.ai_request_id), citations, now)
        return KnowledgeAnswer(
            answer=draft.answer,
            grounded=True,
            simulated=result.simulated,
            model=result.model,
            citations=citations,
        )

    async def _store_retrieval(
        self,
        actor: User,
        question: str,
        ai_request_id: UUID | None,
        citations: list[Citation],
        now: datetime,
    ) -> None:
        await self._retrievals.add(
            retrieval_id=uuid7(),
            organization_id=actor.organization_id,
            question=question,
            ai_request_id=ai_request_id,
            retrieved=[
                {
                    "chunk_id": str(c.chunk_id),
                    "document_title": c.document_title,
                    "document_version": c.document_version,
                    "score": c.score,
                    "used": c.used,
                }
                for c in citations
            ],
            created_at=now,
        )
