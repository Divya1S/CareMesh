"""Consumer for conversation events.

S3 scope: this worker is the delivery skeleton that later phases plug real
logic into (risk analysis arrives in S6). What it does today is real and
minimal: validate the envelope, record idempotent processing in
processed_events, and route poison messages to the dead letter topic after
bounded retries. It never logs message content.

Run: uv run python -m app.workers.conversation_consumer
"""

import asyncio
from datetime import UTC, datetime

import structlog
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.events.kafka import create_consumer, create_producer
from app.infrastructure.events.schemas import EventEnvelope, dlq_topic_for, topic_for
from app.infrastructure.logging import configure_logging
from app.infrastructure.models import ProcessedEventRow
from app.infrastructure.settings import get_settings

GROUP_ID = "caremesh-conversation-worker"

logger = structlog.get_logger()


async def mark_processed(session_factory: async_sessionmaker, envelope: EventEnvelope) -> bool:
    """Records the event as processed. Returns False if it was already
    processed by this group (at least once delivery, exactly once effect)."""
    async with session_factory() as session:
        result = await session.execute(
            pg_insert(ProcessedEventRow)
            .values(
                consumer_group=GROUP_ID,
                event_id=envelope.event_id,
                processed_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["consumer_group", "event_id"])
        )
        await session.commit()
        return result.rowcount == 1


async def handle_raw(
    raw: bytes,
    session_factory: async_sessionmaker,
    producer,
    source_topic: str,
    max_attempts: int,
) -> str:
    """Processes one record. Returns 'processed', 'duplicate', or 'dlq'."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            envelope = EventEnvelope.model_validate_json(raw)
        except ValidationError as exc:
            # Malformed payloads never become valid; retrying is pointless.
            last_error = exc
            break
        try:
            if not await mark_processed(session_factory, envelope):
                logger.info(
                    "event_duplicate_skipped",
                    event_id=str(envelope.event_id),
                    event_type=envelope.event_type,
                )
                return "duplicate"
            logger.info(
                "event_processed",
                event_id=str(envelope.event_id),
                event_type=envelope.event_type,
                correlation_id=envelope.correlation_id,
            )
            return "processed"
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(min(2**attempt * 0.1, 2.0))
    dlq = dlq_topic_for(source_topic)
    await producer.send_and_wait(dlq, raw)
    logger.error(
        "event_dead_lettered",
        topic=source_topic,
        dlq=dlq,
        error_type=type(last_error).__name__ if last_error else "unknown",
    )
    return "dlq"


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    topic = topic_for(settings.kafka_topic_prefix, "PatientMessageCreated")
    consumer = create_consumer(
        topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=GROUP_ID,
    )
    producer = create_producer(settings.kafka_bootstrap_servers)
    await consumer.start()
    await producer.start()
    logger.info("consumer_started", topic=topic, group=GROUP_ID)
    try:
        async for record in consumer:
            await handle_raw(
                record.value,
                session_factory,
                producer,
                source_topic=topic,
                max_attempts=settings.consumer_max_attempts,
            )
            await consumer.commit()
    finally:
        await consumer.stop()
        await producer.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
