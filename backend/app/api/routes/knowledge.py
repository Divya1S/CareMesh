from fastapi import APIRouter, Depends

from app.api.deps import (
    CorrelationIdDep,
    CurrentUserDep,
    KnowledgeServiceDep,
    enforce_ai_rate_limit,
)
from app.api.schemas import (
    AskRequest,
    AskResponse,
    CitationResponse,
    DocumentIngestRequest,
    DocumentIngestResponse,
    KnowledgeDocumentResponse,
)
from app.domain.knowledge import Document

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _document(d: Document) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse(
        id=d.id,
        title=d.title,
        source_name=d.source_name,
        version=d.version,
        created_at=d.created_at,
    )


@router.get("/documents", response_model=list[KnowledgeDocumentResponse])
async def list_documents(
    user: CurrentUserDep, service: KnowledgeServiceDep
) -> list[KnowledgeDocumentResponse]:
    return [_document(d) for d in await service.list_documents(user)]


@router.post("/documents", response_model=DocumentIngestResponse, status_code=201)
async def ingest_document(
    body: DocumentIngestRequest, user: CurrentUserDep, service: KnowledgeServiceDep
) -> DocumentIngestResponse:
    document, chunk_count = await service.ingest(user, body.title, body.source_name, body.content)
    return DocumentIngestResponse(
        document=_document(document), chunk_count=chunk_count, unchanged=chunk_count == 0
    )


@router.post("/ask", response_model=AskResponse, dependencies=[Depends(enforce_ai_rate_limit)])
async def ask(
    body: AskRequest,
    user: CurrentUserDep,
    service: KnowledgeServiceDep,
    correlation_id: CorrelationIdDep,
) -> AskResponse:
    result = await service.ask(user, body.question, correlation_id)
    return AskResponse(
        answer=result.answer,
        grounded=result.grounded,
        simulated=result.simulated,
        model=result.model,
        citations=[
            CitationResponse(
                chunk_id=c.chunk_id,
                document_title=c.document_title,
                document_version=c.document_version,
                snippet=c.snippet,
                score=c.score,
                used=c.used,
            )
            for c in result.citations
        ],
    )
