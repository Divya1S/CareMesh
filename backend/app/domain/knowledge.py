"""Knowledge domain: documents, chunks, and text processing for RAG.

Chunking is deterministic domain logic with unit tests. Retrieval quality
comes from real similarity search over these chunks, never from dumping
whole documents into a prompt.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class DocumentStatus(StrEnum):
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class Document:
    id: UUID
    organization_id: UUID
    title: str
    # Stable identity across versions; a re-ingest of the same source_name
    # creates the next version and supersedes the previous one.
    source_name: str
    version: int
    status: DocumentStatus
    content_sha256: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    id: UUID
    document_id: UUID
    organization_id: UUID
    chunk_index: int
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk: DocumentChunk
    document_title: str
    document_version: int
    score: float


def normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines()]
    collapsed: list[str] = []
    for line in lines:
        if line:
            collapsed.append(" ".join(line.split()))
        elif collapsed and collapsed[-1] != "":
            collapsed.append("")
    return "\n".join(collapsed).strip()


def chunk_text(text: str, max_chars: int = 800, overlap_chars: int = 120) -> list[str]:
    """Splits on paragraph boundaries, packing paragraphs into chunks up to
    max_chars, with a tail overlap so context is not lost at boundaries."""
    normalized = normalize_text(text)
    if not normalized:
        return []
    paragraphs = [p for p in normalized.split("\n") if p]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = current[-overlap_chars:] + "\n" + paragraph
        else:
            # A single paragraph longer than max_chars is split hard.
            for start in range(0, len(paragraph), max_chars - overlap_chars):
                chunks.append(paragraph[start : start + max_chars])
            current = ""
    if current:
        chunks.append(current)
    return chunks
