"""Consumer for conversation events: risk analysis (S6).

On PatientMessageCreated with a patient sender, the message is classified
through the AI Gateway and deterministic thresholds decide whether a Risk
Escalation workflow starts. Three phases per event:

1. Read phase, short transaction: a cheap duplicate check and the message.
2. Model phase, no transaction held: the classifier call, which can take
   seconds on a real provider. The crisis phrase floor is evaluated here
   too, before the model, so a model failure never silences a disclosure.
3. Write phase, one transaction: the idempotency mark (authoritative,
   ON CONFLICT DO NOTHING) and every effect (signal, workflow, outbox
   events) commit together, so a crash before commit replays cleanly and
   a duplicate delivery is skipped. A duplicate that races past the read
   phase costs one wasted model call and nothing else.

Message content never appears in logs or event payloads.

Run: uv run python -m app.workers.conversation_consumer
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import structlog
from aiokafka import TopicPartition
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ai.gateway import AIGateway
from app.application.errors import NotFoundError
from app.application.use_cases.risk_analysis import (
    RiskAnalysisService,
    RiskClassification,
    RiskClassifier,
)
from app.domain.events import PATIENT_MESSAGE_CREATED
from app.infrastructure.ai.factory import create_provider
from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.events.kafka import create_consumer, create_producer
from app.infrastructure.events.schemas import EventEnvelope, dlq_topic_for, topic_for
from app.infrastructure.logging import configure_logging
from app.infrastructure.models import ProcessedEventRow
from app.infrastructure.repositories import (
    SqlAIRequestLog,
    SqlEventOutbox,
    SqlMessageRepository,
    SqlRiskRepository,
    SqlWorkflowRepository,
)
from app.infrastructure.settings import get_settings

GROUP_ID = "caremesh-conversation-worker"

logger = structlog.get_logger()


async def _already_processed(session: AsyncSession, envelope: EventEnvelope) -> bool:
    """Read only pre check so a redelivered event skips the model call. The
    insert in _mark_processed stays the authoritative decision."""
    row = await session.scalar(
        select(ProcessedEventRow.event_id).where(
            ProcessedEventRow.consumer_group == GROUP_ID,
            ProcessedEventRow.event_id == envelope.event_id,
        )
    )
    return row is not None


async def _mark_processed(session: AsyncSession, envelope: EventEnvelope) -> bool:
    """Inserts the idempotency mark in the CALLER'S transaction. Returns
    False when this group already processed the event."""
    result = await session.execute(
        pg_insert(ProcessedEventRow)
        .values(
            consumer_group=GROUP_ID,
            event_id=envelope.event_id,
            processed_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["consumer_group", "event_id"])
    )
    return result.rowcount == 1


def _needs_risk_analysis(envelope: EventEnvelope) -> bool:
    return (
        envelope.event_type == PATIENT_MESSAGE_CREATED
        and envelope.payload.get("sender_type") == "patient"
    )


def _log_duplicate(envelope: EventEnvelope) -> None:
    logger.info(
        "event_duplicate_skipped",
        event_id=str(envelope.event_id),
        event_type=envelope.event_type,
    )


async def process_envelope(
    envelope: EventEnvelope, session_factory: async_sessionmaker, gateway: AIGateway
) -> str:
    """One event. Returns 'processed' or 'duplicate'. Raises on failure so
    the caller can retry and dead letter; a failed attempt leaves no state."""
    classification: RiskClassification | None = None
    if _needs_risk_analysis(envelope):
        async with session_factory() as session:
            if await _already_processed(session, envelope):
                _log_duplicate(envelope)
                return "duplicate"
            message = await SqlMessageRepository(session).get_by_id(
                UUID(envelope.payload["message_id"])
            )
        if message is None:
            raise NotFoundError(f"Message {envelope.payload['message_id']} not found")
        # No transaction is open here: a slow provider must not pin a
        # database connection or hold the idempotency row lock.
        classification = await RiskClassifier(gateway).classify(
            content=message.content,
            organization_id=envelope.organization_id,
            correlation_id=envelope.correlation_id,
        )

    async with session_factory() as session:
        if not await _mark_processed(session, envelope):
            await session.rollback()
            _log_duplicate(envelope)
            return "duplicate"
        if classification is not None:
            signal = await RiskAnalysisService(
                risks=SqlRiskRepository(session),
                workflows=SqlWorkflowRepository(session),
                outbox=SqlEventOutbox(session),
            ).record(
                classification=classification,
                message_id=UUID(envelope.payload["message_id"]),
                conversation_id=UUID(envelope.payload["conversation_id"]),
                patient_id=UUID(envelope.payload["patient_id"]),
                organization_id=envelope.organization_id,
                correlation_id=envelope.correlation_id,
                causation_id=str(envelope.event_id),
            )
            logger.info(
                "risk_signal_stored",
                risk_signal_id=str(signal.id),
                category=signal.category.value,
                severity=signal.severity,
                floor_only=classification.floor_only,
                correlation_id=envelope.correlation_id,
            )
        await session.commit()
    logger.info(
        "event_processed",
        event_id=str(envelope.event_id),
        event_type=envelope.event_type,
        correlation_id=envelope.correlation_id,
    )
    return "processed"


async def handle_raw(
    raw: bytes,
    session_factory: async_sessionmaker,
    producer,
    gateway: AIGateway,
    source_topic: str,
    max_attempts: int,
) -> str:
    """Processes one record with bounded retries, then dead letters it.
    Returns 'processed', 'duplicate', or 'dlq'. Raises only when the dead
    letter publish itself fails, so the caller can hold its position."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            envelope = EventEnvelope.model_validate_json(raw)
        except ValidationError as exc:
            # Malformed payloads never become valid; retrying is pointless.
            last_error = exc
            break
        try:
            return await process_envelope(envelope, session_factory, gateway)
        except Exception as exc:  # transient infra or AI errors retry
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


async def handle_record(
    consumer,
    record,
    session_factory: async_sessionmaker,
    producer,
    gateway: AIGateway,
    *,
    source_topic: str,
    max_attempts: int,
) -> str:
    """One record from the broker, committed only after it was processed,
    skipped as a duplicate, or dead lettered. If even dead lettering fails
    (broker trouble), the consumer seeks back to the record so the next
    poll delivers it again: a record is never skipped, because a skipped
    record here is a message nobody scanned."""
    try:
        outcome = await handle_raw(
            record.value,
            session_factory,
            producer,
            gateway,
            source_topic=source_topic,
            max_attempts=max_attempts,
        )
    except Exception as exc:
        logger.error(
            "consumer_record_held",
            error_type=type(exc).__name__,
            partition=record.partition,
            offset=record.offset,
        )
        consumer.seek(TopicPartition(record.topic, record.partition), record.offset)
        return "held"
    await consumer.commit()
    return outcome


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    # The audit log gets its own small pool: a request log write must never
    # wait on the connection its own transaction is holding.
    audit_engine = create_engine(settings.database_url, pool_size=2, max_overflow=2)
    gateway = AIGateway(
        create_provider(settings.llm_provider),
        SqlAIRequestLog(create_session_factory(audit_engine)),
        timeout_seconds=settings.ai_timeout_seconds,
    )
    topic = topic_for(settings.kafka_topic_prefix, PATIENT_MESSAGE_CREATED)
    consumer = create_consumer(
        topic, bootstrap_servers=settings.kafka_bootstrap_servers, group_id=GROUP_ID
    )
    producer = create_producer(settings.kafka_bootstrap_servers)
    await consumer.start()
    await producer.start()
    logger.info("consumer_started", topic=topic, group=GROUP_ID)
    try:
        # Outer loop: a broken consume stream (rebalance, broker restart)
        # logs and resumes; it must never kill the process, because risk
        # analysis silently stopping is the worst failure this worker has.
        while True:
            try:
                async for record in consumer:
                    outcome = await handle_record(
                        consumer,
                        record,
                        session_factory,
                        producer,
                        gateway,
                        source_topic=topic,
                        max_attempts=settings.consumer_max_attempts,
                    )
                    if outcome == "held":
                        await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("consumer_stream_failed", error_type=type(exc).__name__)
                await asyncio.sleep(2.0)
    finally:
        await consumer.stop()
        await producer.stop()
        await engine.dispose()
        await audit_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
