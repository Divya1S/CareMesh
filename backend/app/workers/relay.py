"""Outbox relay (ADR 0003): polls domain_event_log for unpublished rows and
publishes them to Redpanda, then marks them published.

Run: uv run python -m app.workers.relay
"""

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.events.kafka import create_producer
from app.infrastructure.events.schemas import EventEnvelope, topic_for
from app.infrastructure.logging import configure_logging
from app.infrastructure.models import DomainEventLogRow
from app.infrastructure.settings import get_settings

logger = structlog.get_logger()


async def relay_once(session: AsyncSession, producer, topic_prefix: str, batch_size: int) -> int:
    """Publishes one batch. Returns the number of events published.

    FOR UPDATE SKIP LOCKED lets several relay instances run without publishing
    the same row twice in one poll; consumers stay idempotent regardless.
    """
    rows = (
        await session.scalars(
            select(DomainEventLogRow)
            .where(DomainEventLogRow.published_at.is_(None))
            .order_by(DomainEventLogRow.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not rows:
        return 0
    for row in rows:
        envelope = EventEnvelope(
            event_id=row.id,
            event_type=row.event_type,
            schema_version=row.schema_version,
            occurred_at=row.occurred_at,
            organization_id=row.organization_id,
            correlation_id=row.correlation_id,
            causation_id=row.causation_id,
            payload=row.payload,
        )
        topic = topic_for(topic_prefix, row.event_type)
        await producer.send_and_wait(
            topic,
            envelope.model_dump_json().encode(),
            key=str(row.organization_id).encode(),
        )
        logger.info(
            "event_published",
            event_type=row.event_type,
            topic=topic,
            event_id=str(row.id),
            correlation_id=row.correlation_id,
        )
    now = datetime.now(UTC)
    await session.execute(
        update(DomainEventLogRow)
        .where(DomainEventLogRow.id.in_([r.id for r in rows]))
        .values(published_at=now)
    )
    await session.commit()
    return len(rows)


async def run_relay(
    session_factory: async_sessionmaker,
    producer,
    *,
    poll_seconds: float,
    topic_prefix: str,
    batch_size: int,
) -> None:
    while True:
        async with session_factory() as session:
            published = await relay_once(session, producer, topic_prefix, batch_size)
        if published == 0:
            await asyncio.sleep(poll_seconds)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    producer = create_producer(settings.kafka_bootstrap_servers)
    await producer.start()
    logger.info("relay_started", bootstrap=settings.kafka_bootstrap_servers)
    try:
        await run_relay(
            session_factory,
            producer,
            poll_seconds=settings.relay_poll_seconds,
            topic_prefix=settings.kafka_topic_prefix,
            batch_size=settings.relay_batch_size,
        )
    finally:
        await producer.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
