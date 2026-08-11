"""P14: rate limiting and the audit trail."""

import uuid

import pytest
from sqlalchemy import select

from app.application.use_cases.auth import mask_email
from app.infrastructure.models import AuditLogRow
from app.infrastructure.rate_limit import RedisRateLimiter
from tests.integration.test_risk_flow import post_and_get_envelope, run_consumer

pytestmark = pytest.mark.integration


def test_mask_email_keeps_investigation_value_only():
    assert mask_email("student@demo.caremesh.org") == "st***@demo.caremesh.org"
    assert mask_email("a@b.c") == "a***@b.c"


async def test_rate_limiter_counts_and_recovers(app):
    limiter = RedisRateLimiter(app.state.redis)
    key = f"test:{uuid.uuid4()}"
    for _ in range(3):
        decision = await limiter.allow(key, limit=3, window_seconds=60)
        assert decision.allowed
    denied = await limiter.allow(key, limit=3, window_seconds=60)
    assert not denied.allowed
    assert 1 <= denied.retry_after_seconds <= 60


async def test_login_brute_force_returns_429_with_retry_after(client, app, seeded):
    email = f"target-{uuid.uuid4()}@a.caremesh.org"
    # Exhaust the window directly (the suite runs with a raised limit; the
    # route logic is identical for any configured limit).
    from app.infrastructure.settings import get_settings

    limit = get_settings().login_attempts_per_minute
    # Exhaust the per account bucket; the per address bucket is a separate
    # independent key (two buckets since the final review).
    await app.state.redis.set(f"rl:login:acct:{email}", limit, ex=60)

    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "whatever"}
    )
    assert response.status_code == 429
    assert response.headers.get("retry-after")
    assert response.json()["title"] == "Too many requests"


async def audit_rows(app) -> list[AuditLogRow]:
    async with app.state.session_factory() as session:
        return list(await session.scalars(select(AuditLogRow).order_by(AuditLogRow.id)))


async def test_failed_login_is_audited_without_full_email(client, app, seeded):
    await client.post(
        "/api/v1/auth/login",
        json={"email": "patient@a.caremesh.org", "password": "wrong"},
    )
    rows = await audit_rows(app)
    failed = [r for r in rows if r.action == "login_failed"]
    assert len(failed) == 1
    assert failed[0].actor_id is None
    assert failed[0].detail["email_masked"] == "pa***@a.caremesh.org"
    assert "patient@a" not in str(failed[0].detail)


async def test_successful_login_and_review_decision_are_audited(client, app, seeded, auth_header):
    envelope = await post_and_get_envelope(
        client, app, auth_header, "I keep thinking about hurting myself"
    )
    await run_consumer(app, envelope)
    therapist = await auth_header("therapist@a.caremesh.org")
    queue = (await client.get("/api/v1/reviews", headers=therapist)).json()
    await client.post(
        f"/api/v1/reviews/{queue[0]['workflow_id']}",
        json={"decision": "accept"},
        headers=therapist,
    )

    rows = await audit_rows(app)
    actions = [r.action for r in rows]
    assert "login_success" in actions
    decided = [r for r in rows if r.action == "review_decided"]
    assert len(decided) == 1
    assert decided[0].actor_id == seeded["therapist"].id
    assert decided[0].detail["decision"] == "accept"
    assert decided[0].resource_type == "risk_signal"


async def test_event_republish_is_audited(client, app, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    conversation = (
        await client.post("/api/v1/conversations", json={"title": "a"}, headers=headers)
    ).json()
    await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "hello"},
        headers=headers,
    )
    ops = await auth_header("ops@a.caremesh.org")
    events = (await client.get("/api/v1/ops/events", headers=ops)).json()
    # Mark one published, then republish it through the ops API.
    from datetime import UTC, datetime

    from sqlalchemy import update

    from app.infrastructure.models import DomainEventLogRow

    async with app.state.session_factory() as session:
        await session.execute(
            update(DomainEventLogRow)
            .where(DomainEventLogRow.id == events[0]["id"])
            .values(published_at=datetime.now(UTC))
        )
        await session.commit()
    response = await client.post(f"/api/v1/ops/events/{events[0]['id']}/republish", headers=ops)
    assert response.status_code == 204

    rows = await audit_rows(app)
    republished = [r for r in rows if r.action == "event_republished"]
    assert len(republished) == 1
    assert republished[0].actor_id == seeded["ops"].id
