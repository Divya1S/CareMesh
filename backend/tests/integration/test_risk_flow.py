"""The S6 slice: message, risk signal, deterministic escalation, workflow,
and the clinician review. Runs the consumer logic directly against Postgres
with the fake provider."""

import json

import pytest
from sqlalchemy import select

from app.application.ai.gateway import AIGateway
from app.application.ai.types import LLMResponse
from app.domain.events import PATIENT_MESSAGE_CREATED
from app.infrastructure.ai.fake_provider import FakeLLMProvider
from app.infrastructure.events.schemas import EventEnvelope, dlq_topic_for, topic_for
from app.infrastructure.models import (
    AIRequestRow,
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


async def run_consumer(app, envelope, gateway=None) -> str:
    return await process_envelope(envelope, app.state.session_factory, gateway or make_gateway(app))


class FailingProvider:
    """A provider that is down. Simulated so the eval gate stays honest."""

    name = "failing"
    model_name = "failing-1"
    simulated = True

    async def complete(self, request):
        raise RuntimeError("provider down")


class UnderClassifyingProvider:
    """A steered or broken model that calls everything harmless."""

    name = "steered"
    model_name = "steered-1"
    simulated = True

    async def complete(self, request):
        return LLMResponse(
            text=json.dumps(
                {"category": "none", "severity": 0, "confidence": 0.95, "evidence": ""}
            ),
            model=self.model_name,
            provider=self.name,
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            simulated=True,
        )


def gateway_with(app, provider) -> AIGateway:
    return AIGateway(provider, SqlAIRequestLog(app.state.session_factory), timeout_seconds=5.0)


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


async def test_crisis_phrase_escalates_even_when_the_model_is_down(
    client, app, seeded, auth_header
):
    """The deterministic floor must not depend on the model. With the
    provider down, an explicit disclosure still opens a review workflow,
    the failed model call is audited, and the signal says where it came
    from."""
    envelope = await post_and_get_envelope(client, app, auth_header, "honestly I want to die")
    outcome = await run_consumer(app, envelope, gateway_with(app, FailingProvider()))
    assert outcome == "processed"

    async with app.state.session_factory() as session:
        signal = await session.scalar(select(RiskSignalRow))
        workflow = await session.scalar(select(WorkflowInstanceRow))
        transitions = (await session.scalars(select(WorkflowTransitionRow))).all()
        audited = (
            await session.scalars(
                select(AIRequestRow).where(AIRequestRow.prompt_name == "risk_signal")
            )
        ).all()
        events = {e.event_type for e in (await session.scalars(select(DomainEventLogRow))).all()}

    assert signal is not None
    assert signal.model == "crisis-phrase-floor" and signal.ai_request_id is None
    assert signal.category.value == "crisis" and signal.severity == 3
    assert signal.evidence == "want to die"
    assert workflow is not None and workflow.state == "pending_review"
    assert "crisis phrase floor" in transitions[0].reason
    assert "RiskReviewRequired" in events
    assert len(audited) == 1 and audited[0].status == "provider_error"

    # The therapist sees it like any other escalation.
    therapist = await auth_header("therapist@a.caremesh.org")
    queue = (await client.get("/api/v1/reviews", headers=therapist)).json()
    assert len(queue) == 1 and queue[0]["model"] == "crisis-phrase-floor"


async def test_non_crisis_message_with_model_down_is_dead_lettered_without_state(
    client, app, seeded, auth_header
):
    """Without a floor match there is nothing deterministic to say, so the
    event retries and dead letters exactly as before, leaving no partial
    state."""
    envelope = await post_and_get_envelope(client, app, auth_header, "hello there friend")
    producer = RecordingProducer()
    outcome = await handle_raw(
        envelope.model_dump_json().encode(),
        app.state.session_factory,
        producer,
        gateway_with(app, FailingProvider()),
        source_topic=TOPIC,
        max_attempts=2,
    )
    assert outcome == "dlq"
    async with app.state.session_factory() as session:
        assert await session.scalar(select(RiskSignalRow)) is None
        assert await session.scalar(select(WorkflowInstanceRow)) is None


async def test_floor_overrides_an_under_classifying_model(client, app, seeded, auth_header):
    """A model that calls a crisis disclosure harmless can only add
    escalations, never remove them: the floor still opens review."""
    envelope = await post_and_get_envelope(
        client, app, auth_header, "I keep thinking about hurting myself"
    )
    outcome = await run_consumer(app, envelope, gateway_with(app, UnderClassifyingProvider()))
    assert outcome == "processed"
    async with app.state.session_factory() as session:
        signal = await session.scalar(select(RiskSignalRow))
        workflow = await session.scalar(select(WorkflowInstanceRow))
        detected = await session.scalar(
            select(DomainEventLogRow).where(DomainEventLogRow.event_type == "RiskSignalDetected")
        )
    # The model's (wrong) answer is recorded faithfully with its provenance.
    assert signal.category.value == "none" and signal.model == "steered-1"
    assert signal.prompt_version == 1 and signal.ai_request_id is not None
    # And the floor escalated regardless.
    assert workflow is not None and workflow.state == "pending_review"
    assert detected.payload["escalated"] is True


class StubRecord:
    def __init__(self, value: bytes, topic: str = TOPIC, partition: int = 0, offset: int = 7):
        self.value, self.topic, self.partition, self.offset = value, topic, partition, offset


class StubConsumer:
    def __init__(self) -> None:
        self.commits = 0
        self.seeks: list[tuple[int, int]] = []

    async def commit(self) -> None:
        self.commits += 1

    def seek(self, partition, offset) -> None:
        self.seeks.append((partition.partition, offset))


class BrokenProducer:
    async def send_and_wait(self, topic, value, **kwargs) -> None:
        raise ConnectionError("broker unreachable")


async def test_failed_dead_letter_publish_holds_the_record(app, seeded):
    """When even the DLQ publish fails, the consumer must seek back to the
    record and not commit past it. A skipped record is an unscanned
    message."""
    from app.workers.conversation_consumer import handle_record

    consumer = StubConsumer()
    outcome = await handle_record(
        consumer,
        StubRecord(b"not an envelope"),
        app.state.session_factory,
        BrokenProducer(),
        make_gateway(app),
        source_topic=TOPIC,
        max_attempts=1,
    )
    assert outcome == "held"
    assert consumer.commits == 0
    assert consumer.seeks == [(0, 7)]

    # With a working producer the poison record dead letters and commits.
    producer = RecordingProducer()
    outcome = await handle_record(
        consumer,
        StubRecord(b"not an envelope"),
        app.state.session_factory,
        producer,
        make_gateway(app),
        source_topic=TOPIC,
        max_attempts=1,
    )
    assert outcome == "dlq" and consumer.commits == 1 and len(producer.sent) == 1
