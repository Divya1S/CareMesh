"""Re-embeds every document chunk with the configured embedding provider.

Run after switching EMBEDDING_PROVIDER (ADR 0006), for example:

    EMBEDDING_PROVIDER=fastembed uv run python -m scripts.reingest

Chunk text and document versions are untouched; only vectors and the
provider tag change, so retrieval immediately uses the new space.
"""

import asyncio

import structlog

from app.infrastructure.ai.embeddings import create_embedding_provider
from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.repositories import SqlChunkRepository
from app.infrastructure.settings import get_settings

BATCH = 32


async def reingest() -> None:
    settings = get_settings()
    log = structlog.get_logger()
    embedder = create_embedding_provider(settings.embedding_provider)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        chunks = SqlChunkRepository(session)
        rows = await chunks.all_for_reingest()
        log.info("reingest_start", chunks=len(rows), provider=embedder.name)
        for start in range(0, len(rows), BATCH):
            batch = rows[start : start + BATCH]
            embeddings = embedder.embed([row.content for row in batch])
            await chunks.update_embeddings([row.id for row in batch], embeddings, embedder.name)
        await session.commit()
    await engine.dispose()
    log.info("reingest_done", chunks=len(rows), provider=embedder.name)


if __name__ == "__main__":
    asyncio.run(reingest())
