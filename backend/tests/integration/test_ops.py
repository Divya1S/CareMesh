"""Ops console API: inspection is ops_admin only and org scoped; event
republish clears published_at so the relay sends it again."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update

from app.infrastructure.models import DomainEventLogRow
from tests.integration.test_risk_flow import post_and_get_envelope, run_consumer

pytestmark = pytest.mark.integration


async def drive_crisis(client, app, auth_header):
    envelope = await post_and_get_envelope(
        client, app, auth_header, "I keep thinking about hurting myself"
    )
    await run_consumer(app, envelope)


async def test_ops_endpoints_require_ops_admin(client, seeded, auth_header):
    for email in ("patient@a.caremesh.org", "therapist@a.caremesh.org"):
        headers = await auth_header(email)
        for path in ("/api/v1/ops/workflows", "/api/v1/ops/ai-requests", "/api/v1/ops/events"):
            response = await client.get(path, headers=headers)
            assert response.status_code == 403, f"{email} reached {path}"


async def test_ops_sees_workflows_with_history(client, app, seeded, auth_header):
    await drive_crisis(client, app, auth_header)
    ops = await auth_header("ops@a.caremesh.org")

    workflows = (await client.get("/api/v1/ops/workflows", headers=ops)).json()
    assert len(workflows) == 1
    assert workflows[0]["state"] == "pending_review"
    assert workflows[0]["workflow_type"] == "risk_escalation"

    detail = (await client.get(f"/api/v1/ops/workflows/{workflows[0]['id']}", headers=ops)).json()
    assert [t["to_state"] for t in detail["transitions"]] == ["pending_review"]
    assert detail["transitions"][0]["actor"] == "system"

    filtered = (await client.get("/api/v1/ops/workflows?state=resolved", headers=ops)).json()
    assert filtered == []


async def test_ops_ai_request_inspector(client, app, seeded, auth_header):
    await drive_crisis(client, app, auth_header)
    ops = await auth_header("ops@a.caremesh.org")

    requests = (await client.get("/api/v1/ops/ai-requests", headers=ops)).json()
    prompts = {r["prompt_name"] for r in requests}
    assert prompts == {"dira_reply", "risk_signal"}
    assert all(r["simulated"] for r in requests)
    assert all(r["cost_usd"] == 0.0 for r in requests)

    detail = (await client.get(f"/api/v1/ops/ai-requests/{requests[0]['id']}", headers=ops)).json()
    assert detail["response_text"]
    assert detail["request_messages"][0]["role"] == "system"


async def test_ops_event_republish(client, app, seeded, auth_header):
    await drive_crisis(client, app, auth_header)
    ops = await auth_header("ops@a.caremesh.org")

    # Pretend the relay already published one event, then republish it.
    async with app.state.session_factory() as session:
        row = await session.scalar(select(DomainEventLogRow))
        await session.execute(
            update(DomainEventLogRow)
            .where(DomainEventLogRow.id == row.id)
            .values(published_at=datetime.now(UTC))
        )
        await session.commit()
        event_id = row.id

    events = (await client.get("/api/v1/ops/events", headers=ops)).json()
    published = [e for e in events if e["id"] == str(event_id)]
    assert published and published[0]["published_at"] is not None

    response = await client.post(f"/api/v1/ops/events/{event_id}/republish", headers=ops)
    assert response.status_code == 204

    async with app.state.session_factory() as session:
        row = await session.get(DomainEventLogRow, event_id)
    assert row.published_at is None, "republish must hand the event back to the relay"


async def test_ops_dlq_view(client, seeded, auth_header):
    ops = await auth_header("ops@a.caremesh.org")
    response = await client.get("/api/v1/ops/dlq", headers=ops)
    assert response.status_code == 200
    body = response.json()
    assert body["topic"].endswith(".dlq")
    assert isinstance(body["records"], list)
