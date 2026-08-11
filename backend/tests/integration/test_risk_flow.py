"""The S6 slice: message, risk signal, deterministic escalation, workflow,
and the clinician review. Runs the consumer logic directly against Postgres
with the fake provider."""

import pytest
from sqlalchemy import select

from app.application.ai.gateway import AIGateway
from app.domain.events import PATIENT_MESSAGE_CREATED
from app.infrastructure.ai.fake_provider import FakeLLMProvider
from app.infrastructure.events.schemas import EventEnvelope, dlq_topic_for, topic_for
from app.infrastructure.models import (
    DomainEventLogRow,
    RiskReviewRow,
    RiskSignalRow,
    WorkflowInstanceRow,
    WorkflowTransitionRow,
)
from app.infrastructure.repositories import SqlAIRequestLog
from app.workers.conversation_consumer import handle_raw, process_envelope

pytestmark = pytest.mark.integration

TOPIC = topic_for("caremesh", PATIENT_MESSAGE_CREATED)


class RecordingProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []

    async def send_and_wait(self, topic: str, value: bytes, **kwargs) -> None:
        self.sent.append((topic, value))


def make_gateway(app) -> AIGateway:
    return AIGateway(
        FakeLLMProvider(), SqlAIRequestLog(app.state.session_factory), timeout_seconds=5.0
    )


async def post_and_get_envelope(client, app, auth_header, content) -> EventEnvelope:
    """Posts a patient message through the API and returns the resulting
    PatientMessageCreated envelope from the outbox, as the relay would."""
    headers = await auth_header("patient@a.caremesh.org")
    conversation = (
        await client.post("/api/v1/conversations", json={"title": "t"}, headers=headers)
    ).json()
    posted = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": content},
        headers=headers,
    )
    assert posted.status_code == 201
    async with app.state.session_factory() as session:
        row = await session.scalar(
            select(DomainEventLogRow).where(DomainEventLogRow.event_type == PATIENT_MESSAGE_CREATED)
        )
    return EventEnvelope(
        event_id=row.id,
        event_type=row.event_type,
        schema_version=row.schema_version,
        occurred_at=row.occurred_at,
        organization_id=row.organization_id,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        payload=row.payload,
    )


async def run_consumer(app, envelope) -> str:
    async with app.state.session_factory() as session:
        return await process_envelope(envelope, session, make_gateway(app))


async def test_crisis_message_creates_signal_and_pending_workflow(client, app, seeded, auth_header):
    envelope = await post_and_get_envelope(
        client, app, auth_header, "I keep thinking about hurting myself"
    )
    assert await run_consumer(app, envelope) == "processed"

    async with app.state.session_factory() as session:
        signal = await session.scalar(select(RiskSignalRow))
        workflow = await session.scalar(select(WorkflowInstanceRow))
        transitions = (await session.scalars(select(WorkflowTransitionRow))).all()
        events = (await session.scalars(select(DomainEventLogRow))).all()

    assert signal.category.value == "crisis" and signal.severity == 3
    assert signal.simulated is True
    assert workflow.state == "pending_review"
    assert workflow.subject_id == signal.id
    assert workflow.correlation_id == envelope.correlation_id
    assert [t.to_state for t in transitions] == ["pending_review"]
    types = sorted(e.event_type for e in events)
    assert "RiskSignalDetected" in types and "RiskReviewRequired" in types


async def test_neutral_message_creates_signal_but_no_workflow(client, app, seeded, auth_header):
    envelope = await post_and_get_envelope(client, app, auth_header, "hello there friend")
    assert await run_consumer(app, envelope) == "processed"
    async with app.state.session_factory() as session:
        signal = await session.scalar(select(RiskSignalRow))
        workflow = await session.scalar(select(WorkflowInstanceRow))
    assert signal is not None and signal.severity == 0
    assert workflow is None


async def test_duplicate_delivery_is_skipped(client, app, seeded, auth_header):
    envelope = await post_and_get_envelope(client, app, auth_header, "I feel hopeless")
    assert await run_consumer(app, envelope) == "processed"
    assert await run_consumer(app, envelope) == "duplicate"
    async with app.state.session_factory() as session:
        signals = (await session.scalars(select(RiskSignalRow))).all()
    assert len(signals) == 1


async def test_malformed_ai_output_dead_letters_after_retries(client, app, seeded, auth_header):
    envelope = await post_and_get_envelope(client, app, auth_header, "trigger [[fail:malformed]]")
    producer = RecordingProducer()
    outcome = await handle_raw(
        envelope.model_dump_json().encode(),
        app.state.session_factory,
        producer,
        make_gateway(app),
        source_topic=TOPIC,
        max_attempts=2,
    )
    assert outcome == "dlq"
    assert producer.sent and producer.sent[0][0] == dlq_topic_for(TOPIC)
    async with app.state.session_factory() as session:
        signal = await session.scalar(select(RiskSignalRow))
    assert signal is None, "a failed analysis must not leave partial state"


async def test_review_queue_and_accept_decision(client, app, seeded, auth_header):
    envelope = await post_and_get_envelope(client, app, auth_header, "I want to hurt myself")
    await run_consumer(app, envelope)

    therapist = await auth_header("therapist@a.caremesh.org")
    queue = (await client.get("/api/v1/reviews", headers=therapist)).json()
    assert len(queue) == 1
    item = queue[0]
    assert item["category"] == "crisis" and item["simulated"] is True
    assert item["patient_name"] == "Pat A"
    assert "hurt myself" in item["message_content"]

    decided = await client.post(
        f"/api/v1/reviews/{item['workflow_id']}",
        json={"decision": "accept", "note": "Reaching out now."},
        headers=therapist,
    )
    assert decided.status_code == 200
    assert decided.json()["state"] == "resolved"

    assert (await client.get("/api/v1/reviews", headers=therapist)).json() == []
    async with app.state.session_factory() as session:
        review = await session.scalar(select(RiskReviewRow))
        workflow = await session.scalar(select(WorkflowInstanceRow))
        events = (await session.scalars(select(DomainEventLogRow))).all()
    assert review.decision.value == "accept"
    assert workflow.state == "resolved"
    assert "HumanReviewCompleted" in {e.event_type for e in events}

    # Deciding twice must fail: the workflow is terminal.
    again = await client.post(
        f"/api/v1/reviews/{item['workflow_id']}",
        json={"decision": "reject"},
        headers=therapist,
    )
    assert again.status_code == 422


async def test_review_authorization(client, app, seeded, auth_header):
    envelope = await post_and_get_envelope(client, app, auth_header, "I want to end it")
    await run_consumer(app, envelope)

    unassigned = await auth_header("therapist2@a.caremesh.org")
    assert (await client.get("/api/v1/reviews", headers=unassigned)).json() == []

    patient = await auth_header("patient@a.caremesh.org")
    assert (await client.get("/api/v1/reviews", headers=patient)).status_code == 403

    assigned = await auth_header("therapist@a.caremesh.org")
    queue = (await client.get("/api/v1/reviews", headers=assigned)).json()
    denied = await client.post(
        f"/api/v1/reviews/{queue[0]['workflow_id']}",
        json={"decision": "accept"},
        headers=unassigned,
    )
    assert denied.status_code == 403

    # Edit without a severity override is invalid.
    bad_edit = await client.post(
        f"/api/v1/reviews/{queue[0]['workflow_id']}",
        json={"decision": "edit"},
        headers=assigned,
    )
    assert bad_edit.status_code == 422
