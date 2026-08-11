"""P12: the metrics endpoint exposes real HTTP, AI, and workflow metrics."""

import pytest

from app.infrastructure.gauges import refresh_once
from tests.integration.test_risk_flow import post_and_get_envelope, run_consumer

pytestmark = pytest.mark.integration


async def test_metrics_expose_http_and_ai_activity(client, app, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    conversation = (
        await client.post("/api/v1/conversations", json={"title": "m"}, headers=headers)
    ).json()
    await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "metrics check"},
        headers=headers,
    )

    body = (await client.get("/metrics")).text
    assert "caremesh_http_requests_total" in body
    # Paths are normalized: no raw UUIDs in labels.
    assert 'path="/api/v1/conversations/:id/messages"' in body
    assert conversation["id"] not in body
    # Dira's reply went through the gateway on the fake provider.
    assert 'caremesh_ai_requests_total{prompt="dira_reply"' in body
    assert 'simulated="true"' in body
    assert "caremesh_ai_cost_usd_total 0.0" in body


async def test_gauges_reflect_pending_work(client, app, seeded, auth_header):
    envelope = await post_and_get_envelope(
        client, app, auth_header, "I keep thinking about hurting myself"
    )
    await run_consumer(app, envelope)
    await refresh_once(app.state.session_factory)

    body = (await client.get("/metrics")).text
    assert (
        'caremesh_workflows_by_state{state="pending_review",workflow_type="risk_escalation"} 1.0'
        in body
    )
    assert "caremesh_review_queue_depth 1.0" in body
    # The relay has not run in tests, so outbox events are waiting.
    assert "caremesh_outbox_unpublished 0.0" not in body
