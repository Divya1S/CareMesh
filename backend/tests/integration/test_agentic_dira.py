"""H2: Dira's tool loop and the streaming endpoint."""

import json

import pytest
from sqlalchemy import select

from app.infrastructure.models import (
    AIRequestRow,
    AppointmentRequestRow,
    DomainEventLogRow,
    WorkflowInstanceRow,
)

pytestmark = pytest.mark.integration

SLEEP_DOC = {
    "title": "Sleep and exam season",
    "source_name": "sleep-exam-season",
    "content": (
        "Sleep gets harder exactly when it matters most. During exam season "
        "worry keeps the mind busy at night.\n\nTry keeping a regular wind "
        "down time, with screens away thirty minutes before bed, and write "
        "tomorrow's three biggest tasks on paper before you rest."
    ),
}


async def start_conversation(client, headers):
    response = await client.post("/api/v1/conversations", json={"title": "t"}, headers=headers)
    return response.json()["id"]


async def test_resource_question_runs_the_search_tool(client, app, seeded, auth_header):
    ops = await auth_header("ops@a.caremesh.org")
    await client.post("/api/v1/knowledge/documents", json=SLEEP_DOC, headers=ops)

    patient = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, patient)
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "any tips to sleep better before my test?"},
        headers=patient,
    )
    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=patient)
    ).json()
    dira = messages[-1]
    assert dira["sender_type"] == "dira"
    assert "Sleep and exam season" in dira["content"], "the reply must cite the source"

    async with app.state.session_factory() as session:
        rows = (await session.scalars(select(AIRequestRow))).all()
    tool_rows = [r for r in rows if r.tool_calls]
    assert len(tool_rows) == 1
    assert tool_rows[0].tool_calls[0]["name"] == "search_resources"


async def test_appointment_request_creates_workflow_for_the_care_team(
    client, app, seeded, auth_header
):
    patient = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, patient)
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "could you book a time, I want an appointment with someone"},
        headers=patient,
    )
    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=patient)
    ).json()
    assert "care team" in messages[-1]["content"].lower()

    async with app.state.session_factory() as session:
        request = await session.scalar(select(AppointmentRequestRow))
        workflow = await session.scalar(
            select(WorkflowInstanceRow).where(
                WorkflowInstanceRow.workflow_type == "appointment_request"
            )
        )
        events = {e.event_type for e in (await session.scalars(select(DomainEventLogRow))).all()}
    assert request is not None and workflow.state == "requested"
    assert "AppointmentRequested" in events

    # The assigned therapist sees and acknowledges it; twice fails.
    therapist = await auth_header("therapist@a.caremesh.org")
    pending = (await client.get("/api/v1/appointments", headers=therapist)).json()
    assert len(pending) == 1 and pending[0]["patient_name"] == "Pat A"
    ack = await client.post(
        f"/api/v1/appointments/{pending[0]['request_id']}/acknowledge", headers=therapist
    )
    assert ack.json()["state"] == "acknowledged"
    again = await client.post(
        f"/api/v1/appointments/{pending[0]['request_id']}/acknowledge", headers=therapist
    )
    assert again.status_code == 422
    assert (await client.get("/api/v1/appointments", headers=therapist)).json() == []


async def test_crisis_message_never_detours_into_tools(client, app, seeded, auth_header):
    patient = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, patient)
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "any tips? honestly I keep thinking about hurting myself"},
        headers=patient,
    )
    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=patient)
    ).json()
    assert "crisis" in messages[-1]["content"].lower()
    async with app.state.session_factory() as session:
        rows = (await session.scalars(select(AIRequestRow))).all()
    assert all(not r.tool_calls for r in rows), "crisis replies must be direct"


async def test_streaming_endpoint_emits_tool_delta_and_message_events(
    client, app, seeded, auth_header
):
    patient = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, patient)
    async with client.stream(
        "POST",
        f"/api/v1/conversations/{conversation_id}/messages/stream",
        json={"content": "can I get an appointment please"},
        headers=patient,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = []
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    types = [e["type"] for e in events]
    assert types[0] == "saved"
    assert "tool" in types and "delta" in types and types[-1] == "message"
    tool_event = next(e for e in events if e["type"] == "tool")
    assert tool_event["name"] == "request_appointment"
    final = events[-1]["message"]
    assert final["sender_type"] == "dira" and final["simulated"] is True
    streamed_text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert final["content"] in streamed_text or streamed_text.strip() == final["content"]

    # The reply and the patient message are persisted after the stream.
    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=patient)
    ).json()
    assert [m["sender_type"] for m in messages] == ["patient", "dira"]


async def test_repeated_appointment_requests_create_one_open_request(
    client, app, seeded, auth_header
):
    """The request_appointment tool is idempotent per conversation: a second
    ask while one is open must not create another workflow or row."""
    patient = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, patient)
    for _ in range(2):
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "can you schedule an appointment for me?"},
            headers=patient,
        )
    async with app.state.session_factory() as session:
        requests = (await session.scalars(select(AppointmentRequestRow))).all()
    assert len(requests) == 1


async def test_hostile_request_id_is_replaced_not_stored(client, seeded, auth_header):
    """A client supplied X-Request-ID that would not fit the String(64)
    correlation columns is replaced with a generated id instead of
    truncating an insert into a 500."""
    patient = await auth_header("patient@a.caremesh.org")
    conversation_id = await start_conversation(client, patient)
    hostile = "a" * 100 + "\ninjected-log-line"
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "hello there"},
        headers={**patient, "X-Request-ID": hostile},
    )
    assert response.status_code == 201
    echoed = response.headers.get("x-request-id", "")
    assert echoed != hostile
    assert len(echoed) <= 64
