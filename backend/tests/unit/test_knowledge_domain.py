from datetime import UTC, datetime

from app.application.use_cases.knowledge import rerank
from app.domain.ids import uuid7
from app.domain.knowledge import DocumentChunk, RetrievedChunk, chunk_text, normalize_text
from app.infrastructure.ai.embeddings import EMBEDDING_DIM, LocalLexicalEmbedding


def test_normalize_collapses_whitespace_and_blank_runs():
    text = "  a   line \n\n\n  another   line \n"
    assert normalize_text(text) == "a line\n\nanother line"


def test_short_text_is_one_chunk():
    assert chunk_text("A single short paragraph.") == ["A single short paragraph."]


def test_long_text_chunks_with_overlap():
    paragraphs = "\n\n".join(f"Paragraph {i} " + ("words " * 40) for i in range(8))
    chunks = chunk_text(paragraphs, max_chars=400, overlap_chars=80)
    assert len(chunks) > 1
    assert all(len(c) <= 400 + 81 for c in chunks)
    # Overlap: the start of chunk 2 repeats the tail of chunk 1.
    assert chunks[1][:40] in chunks[0] + chunks[1]


def test_empty_text_gives_no_chunks():
    assert chunk_text("   \n  ") == []


def test_embeddings_are_deterministic_and_normalized():
    embedder = LocalLexicalEmbedding()
    first, second = embedder.embed(["sleep before an exam", "sleep before an exam"])
    assert first == second
    assert len(first) == EMBEDDING_DIM
    norm = sum(v * v for v in first)
    assert abs(norm - 1.0) < 1e-9


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_embeddings_rank_related_text_higher():
    embedder = LocalLexicalEmbedding()
    query, related, unrelated = embedder.embed(
        [
            "how do I sleep better before my exam",
            "Sleep gets harder during exam season; keep a regular wind down time.",
            "The payer submits an insurance claim after the appointment.",
        ]
    )
    assert _cosine(query, related) > _cosine(query, unrelated)


def _retrieved(content: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=DocumentChunk(
            id=uuid7(),
            document_id=uuid7(),
            organization_id=uuid7(),
            chunk_index=0,
            content=content,
            created_at=datetime.now(UTC),
        ),
        document_title="t",
        document_version=1,
        score=score,
    )


def test_rerank_prefers_keyword_matches_on_close_scores():
    on_topic = _retrieved("grounding techniques help with anxious moments", 0.50)
    off_topic = _retrieved("completely different subject entirely", 0.55)
    ranked = rerank("grounding techniques for anxious moments", [off_topic, on_topic])
    assert ranked[0].chunk.content.startswith("grounding")
