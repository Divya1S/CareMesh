"""Dira reply flow (S5): patient messages get a simulated, labeled reply
through the gateway; failures never block the patient's message."""

from uuid import UUID

import pytest
from sqlalchemy import select

from app.infrastructure.models import AIRequestRow, DomainEventLogRow

pytestmark = pytest.mark.integration


async def start_conversation(client, headers, title="check in"):
    response = await client.post("/api/v1/conversations", json={"title": title}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


async def send(client, headers, conversation_id, content):
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


async def messages_of(client, headers, conversation_id):
    response = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=headers
    )
    assert response.status_code == 200
    return response.json()


async def test_patient_message_gets_simulated_dira_reply(client, app, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, headers)
    await send(client, headers, conversation_id, "I have been really sad lately")

    messages = await messages_of(client, headers, conversation_id)
    assert [m["sender_type"] for m in messages] == ["patient", "dira"]
    dira = messages[1]
    assert dira["simulated"] is True, "simulated flag must reach the API"
    assert dira["sender_id"] is None
    assert "heavy" in dira["content"].lower() or len(dira["content"]) > 0

    async with app.state.session_factory() as session:
        ai_rows = (await session.scalars(select(AIRequestRow))).all()
        events = (await session.scalars(select(DomainEventLogRow))).all()
    assert len(ai_rows) == 1
    assert ai_rows[0].prompt_name == "dira_reply" and ai_rows[0].simulated is True
    event_types = sorted(e.event_type for e in events)
    assert event_types == ["AIResponseGenerated", "PatientMessageCreated"]


async def test_dira_reply_uses_conversation_memory(client, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, headers)
    await send(client, headers, conversation_id, "hello there")
    await send(client, headers, conversation_id, "my exam is next week")

    messages = await messages_of(client, headers, conversation_id)
    assert [m["sender_type"] for m in messages] == ["patient", "dira", "patient", "dira"]
    assert "exam" in messages[3]["content"].lower()


async def test_crisis_message_gets_crisis_scenario_reply(client, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, headers)
    await send(client, headers, conversation_id, "I have been thinking about hurting myself")
    messages = await messages_of(client, headers, conversation_id)
    assert messages[1]["sender_type"] == "dira"
    assert "crisis" in messages[1]["content"].lower()


async def test_clinician_message_gets_no_dira_reply(client, seeded, auth_header):
    patient_headers = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, patient_headers)
    therapist_headers = await auth_header("therapist@a.caremesh.org")
    await send(client, therapist_headers, conversation_id, "Checking in on you.")

    messages = await messages_of(client, patient_headers, conversation_id)
    assert [m["sender_type"] for m in messages] == ["clinician"]


async def test_ai_failure_never_blocks_the_patient_message(client, app, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, headers)
    posted = await send(client, headers, conversation_id, "please break [[fail:error]]")
    assert posted["sender_type"] == "patient"

    messages = await messages_of(client, headers, conversation_id)
    assert [m["sender_type"] for m in messages] == ["patient"], "no dira reply on failure"

    async with app.state.session_factory() as session:
        ai_rows = (await session.scalars(select(AIRequestRow))).all()
    assert len(ai_rows) == 1
    assert ai_rows[0].status == "provider_error", "the failure must still be audited"


async def test_dira_memory_tracks_a_long_conversation(client, app, seeded, auth_header):
    """Past the old 100 message page, history must still end with the
    newest message, otherwise Dira replies to stale context and the crisis
    tool guard inspects an old turn."""
    from datetime import UTC, datetime, timedelta

    from app.application.ai.gateway import AIGateway
    from app.application.use_cases.conversations import (
        DIRA_MEMORY_MESSAGES,
        ConversationService,
    )
    from app.domain.entities import Message, SenderType
    from app.domain.ids import uuid7
    from app.infrastructure.ai.fake_provider import FakeLLMProvider
    from app.infrastructure.repositories import (
        SqlAIRequestLog,
        SqlCareAssignmentRepository,
        SqlConversationRepository,
        SqlEventOutbox,
        SqlMessageRepository,
    )

    patient = await auth_header("patient@a.caremesh.org")
    conversation_id = (
        await client.post("/api/v1/conversations", json={"title": "long"}, headers=patient)
    ).json()["id"]

    start = datetime.now(UTC) - timedelta(hours=3)
    async with app.state.session_factory() as session:
        messages = SqlMessageRepository(session)
        for i in range(130):
            await messages.add(
                Message(
                    id=uuid7(),
                    conversation_id=UUID(conversation_id),
                    sender_type=SenderType.PATIENT if i % 2 == 0 else SenderType.DIRA,
                    sender_id=seeded["patient"].id if i % 2 == 0 else None,
                    content=f"message {i}",
                    created_at=start + timedelta(seconds=i),
                )
            )
        await session.commit()

    async with app.state.session_factory() as session:
        service = ConversationService(
            conversations=SqlConversationRepository(session),
            messages=SqlMessageRepository(session),
            assignments=SqlCareAssignmentRepository(session),
            outbox=SqlEventOutbox(session),
            gateway=AIGateway(
                FakeLLMProvider(), SqlAIRequestLog(app.state.session_factory), timeout_seconds=5
            ),
        )
        conversation = await SqlConversationRepository(session).get_by_id(UUID(conversation_id))
        history = await service._build_history(conversation)

    assert len(history) == DIRA_MEMORY_MESSAGES
    assert history[-1].content == "message 129"
    assert history[0].content == f"message {130 - DIRA_MEMORY_MESSAGES}"

    # The API can serve the newest page too, which is what the chat loads.
    newest = (
        await client.get(
            f"/api/v1/conversations/{conversation_id}/messages?order=desc&limit=5",
            headers=patient,
        )
    ).json()
    assert [m["content"] for m in newest] == [f"message {i}" for i in range(129, 124, -1)]


class TransactionProbeProvider:
    """A provider that, while "thinking", counts sessions on the test
    database that sit idle inside an open transaction. The request's own
    session must not be one of them."""

    name = "fake"
    model_name = "fake-sim-1"
    simulated = True

    def __init__(self, session_factory) -> None:
        from app.infrastructure.ai.fake_provider import FakeLLMProvider

        self._inner = FakeLLMProvider()
        self._factory = session_factory
        self.idle_in_transaction: list[int] = []

    async def _probe(self) -> None:
        from sqlalchemy import text

        async with self._factory() as session:
            count = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND state = 'idle in transaction'"
                )
            )
            await session.rollback()
        self.idle_in_transaction.append(int(count or 0))

    async def complete(self, request):
        await self._probe()
        return await self._inner.complete(request)

    async def stream(self, request):
        await self._probe()
        async for item in self._inner.stream(request):
            yield item


async def test_model_calls_hold_no_open_transaction(client, app, seeded, auth_header):
    """Both reply paths release the request's connection before calling
    the model; a slow provider must not pin the pool."""
    from app.application.ai.gateway import AIGateway
    from app.infrastructure.repositories import SqlAIRequestLog

    probe = TransactionProbeProvider(app.state.audit_session_factory)
    app.state.gateway = AIGateway(
        probe, SqlAIRequestLog(app.state.audit_session_factory), timeout_seconds=5.0
    )
    patient = await auth_header("patient@a.caremesh.org")
    conversation_id = (
        await client.post("/api/v1/conversations", json={"title": "t"}, headers=patient)
    ).json()["id"]

    posted = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "hello there"},
        headers=patient,
    )
    assert posted.status_code == 201
    async with client.stream(
        "POST",
        f"/api/v1/conversations/{conversation_id}/messages/stream",
        json={"content": "and again"},
        headers=patient,
    ) as response:
        async for _ in response.aiter_lines():
            pass
    assert probe.idle_in_transaction == [0, 0]
