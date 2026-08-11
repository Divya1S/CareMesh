"""Event pipeline tests: transactional outbox, relay to Redpanda, consumer
idempotency, and dead lettering. Needs docker compose (Postgres and Redpanda)."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.domain.events import patient_message_created
from app.infrastructure.events.kafka import create_consumer, create_producer
from app.infrastructure.events.schemas import EventEnvelope, dlq_topic_for, topic_for
from app.infrastructure.models import DomainEventLogRow
from app.infrastructure.repositories import SqlEventOutbox
from app.workers.conversation_consumer import handle_raw
from app.workers.relay import relay_once

pytestmark = pytest.mark.integration

BOOTSTRAP = "localhost:9092"
TOPIC = topic_for("caremesh", "PatientMessageCreated")


async def find_record(topic: str, predicate, timeout: float = 15.0):
    """Reads the topic from the beginning with a throwaway group until a
    record matches or the timeout passes."""
    consumer = create_consumer(topic, bootstrap_servers=BOOTSTRAP, group_id=f"test-{uuid.uuid4()}")
    await consumer.start()
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            batches = await consumer.getmany(timeout_ms=500)
            for records in batches.values():
                for record in records:
                    if predicate(record.value):
                        return record.value
        return None
    finally:
        await consumer.stop()


def make_event(org_id, correlation_id="test-corr-1"):
    return patient_message_created(
        message_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        sender_type="patient",
        organization_id=org_id,
        occurred_at=datetime.now(UTC),
        correlation_id=correlation_id,
    )


async def test_post_message_writes_outbox_in_same_transaction(client, app, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    conversation = (
        await client.post("/api/v1/conversations", json={"title": "t"}, headers=headers)
    ).json()
    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "hello"},
        headers=headers,
    )
    assert response.status_code == 201
    message = response.json()

    async with app.state.session_factory() as session:
        rows = (await session.scalars(select(DomainEventLogRow))).all()
    by_type = {r.event_type: r for r in rows}
    # The patient message event plus Dira's AIResponseGenerated (S5).
    assert sorted(by_type) == ["AIResponseGenerated", "PatientMessageCreated"]
    row = by_type["PatientMessageCreated"]
    assert row.payload["message_id"] == message["id"]
    assert "content" not in row.payload, "clinical text must not enter events"
    assert row.correlation_id == response.headers["x-request-id"]
    assert row.published_at is None


async def test_relay_publishes_and_marks_published(app, seeded):
    org_id = seeded["org_a"].id
    event = make_event(org_id, correlation_id=f"corr-{uuid.uuid4()}")
    async with app.state.session_factory() as session:
        await SqlEventOutbox(session).add(event)
        await session.commit()

    producer = create_producer(BOOTSTRAP)
    await producer.start()
    try:
        async with app.state.session_factory() as session:
            published = await relay_once(session, producer, "caremesh", 100)
    finally:
        await producer.stop()
    assert published == 1

    async with app.state.session_factory() as session:
        row = await session.get(DomainEventLogRow, event.event_id)
    assert row is not None and row.published_at is not None

    wanted = str(event.event_id)
    raw = await find_record(TOPIC, lambda v: json.loads(v).get("event_id") == wanted)
    assert raw is not None, "event did not arrive on the topic"
    envelope = EventEnvelope.model_validate_json(raw)
    assert envelope.correlation_id == event.correlation_id


async def test_consumer_is_idempotent(app, seeded):
    envelope = EventEnvelope.from_domain(make_event(seeded["org_a"].id))
    raw = envelope.model_dump_json().encode()

    class NoProducer:
        async def send_and_wait(self, *a, **k):
            raise AssertionError("valid events must not be dead lettered")

    factory = app.state.session_factory
    assert await handle_raw(raw, factory, NoProducer(), TOPIC, 3) == "processed"
    assert await handle_raw(raw, factory, NoProducer(), TOPIC, 3) == "duplicate"


async def test_malformed_message_goes_to_dlq(app, seeded):
    marker = f"poison-{uuid.uuid4()}".encode()
    producer = create_producer(BOOTSTRAP)
    await producer.start()
    try:
        outcome = await handle_raw(marker, app.state.session_factory, producer, TOPIC, 3)
    finally:
        await producer.stop()
    assert outcome == "dlq"

    raw = await find_record(dlq_topic_for(TOPIC), lambda v: v == marker)
    assert raw == marker, "poison message did not land on the dead letter topic"
