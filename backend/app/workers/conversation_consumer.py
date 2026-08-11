"""Consumer for conversation events: risk analysis (S6).

On PatientMessageCreated with a patient sender, the Risk Signal agent runs
through the AI Gateway, and deterministic thresholds decide whether a Risk
Escalation workflow starts. The idempotency mark and every effect (signal,
workflow, outbox events) commit in ONE transaction, so a crash before commit
replays cleanly and a duplicate delivery is skipped. Message content never
appears in logs or event payloads.

Run: uv run python -m app.workers.conversation_consumer
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import structlog
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ai.gateway import AIGateway
from app.application.use_cases.risk_analysis import RiskAnalysisService
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


async def process_envelope(
    envelope: EventEnvelope, session: AsyncSession, gateway: AIGateway
) -> str:
    """One event, one transaction. Returns 'processed' or 'duplicate'."""
    if not await _mark_processed(session, envelope):
        await session.rollback()
        logger.info(
            "event_duplicate_skipped",
            event_id=str(envelope.event_id),
            event_type=envelope.event_type,
        )
        return "duplicate"

    if (
        envelope.event_type == PATIENT_MESSAGE_CREATED
        and envelope.payload.get("sender_type") == "patient"
    ):
        service = RiskAnalysisService(
            messages=SqlMessageRepository(session),
            risks=SqlRiskRepository(session),
            workflows=SqlWorkflowRepository(session),
            outbox=SqlEventOutbox(session),
            gateway=gateway,
        )
        signal = await service.analyze_message(
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
    Returns 'processed', 'duplicate', or 'dlq'."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            envelope = EventEnvelope.model_validate_json(raw)
        except ValidationError as exc:
            # Malformed payloads never become valid; retrying is pointless.
            last_error = exc
            break
        try:
            async with session_factory() as session:
                return await process_envelope(envelope, session, gateway)
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


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    gateway = AIGateway(
        create_provider(settings.llm_provider),
        SqlAIRequestLog(session_factory),
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
                    try:
                        await handle_raw(
                            record.value,
                            session_factory,
                            producer,
                            gateway,
                            source_topic=topic,
                            max_attempts=settings.consumer_max_attempts,
                        )
                        await consumer.commit()
                    except Exception as exc:
                        # handle_raw already dead letters processing errors;
                        # this catches commit and DLQ produce failures.
                        logger.error("consumer_iteration_failed", error_type=type(exc).__name__)
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


if __name__ == "__main__":
    asyncio.run(main())
