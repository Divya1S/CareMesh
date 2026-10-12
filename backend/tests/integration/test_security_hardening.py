"""P14: rate limiting and the audit trail."""

import uuid

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from app.application.errors import ServiceUnavailableError
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


class DownRedis:
    """A Redis client whose every call fails, as during an outage."""

    def pipeline(self, transaction=True):
        raise RedisConnectionError("redis is down")

    async def ttl(self, key):
        raise RedisConnectionError("redis is down")

    async def ping(self):
        raise RedisConnectionError("redis is down")


async def test_limiter_failure_policy_is_explicit():
    limiter = RedisRateLimiter(DownRedis())
    with pytest.raises(ServiceUnavailableError):
        await limiter.allow("login:acct:x", limit=5, window_seconds=60, on_failure="closed")
    decision = await limiter.allow("ai:u", limit=5, window_seconds=60, on_failure="open")
    assert decision.allowed


async def test_redis_outage_fails_login_closed_and_chat_open(client, app, seeded, auth_header):
    patient = await auth_header("patient@a.caremesh.org")
    conversation = (
        await client.post("/api/v1/conversations", json={"title": "t"}, headers=patient)
    ).json()
    live_redis = app.state.redis
    app.state.redis = DownRedis()
    try:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "patient@a.caremesh.org", "password": "test-password-1"},
        )
        assert login.status_code == 503
        assert login.headers.get("retry-after")
        assert login.json()["title"] == "Service unavailable"

        posted = await client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={"content": "still here"},
            headers=patient,
        )
        assert posted.status_code == 201, "the AI limiter fails open"

        health = await client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "degraded", "database": "ok", "redis": "unavailable"}
    finally:
        app.state.redis = live_redis


async def test_security_headers_and_no_store_on_api_responses(client, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    health = await client.get("/healthz")
    assert "cache-control" not in health.headers


async def test_metrics_require_the_token_when_one_is_configured(client, monkeypatch):
    from app.infrastructure.settings import get_settings

    monkeypatch.setenv("METRICS_TOKEN", "scrape-secret")
    get_settings.cache_clear()
    try:
        assert (await client.get("/metrics")).status_code == 401
        ok = await client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
        assert ok.status_code == 200
    finally:
        monkeypatch.delenv("METRICS_TOKEN")
        get_settings.cache_clear()


async def test_login_limiter_honors_forwarded_address_only_when_trusted(
    client, app, seeded, monkeypatch
):
    from app.infrastructure.settings import get_settings

    limit = get_settings().login_attempts_per_minute
    await app.state.redis.set("rl:login:addr:203.0.113.9", limit, ex=60)
    body = {"email": "patient@a.caremesh.org", "password": "test-password-1"}
    forwarded = {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}

    # Untrusted by default: the header cannot pick the bucket.
    assert (
        await client.post("/api/v1/auth/login", json=body, headers=forwarded)
    ).status_code == 200

    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    get_settings.cache_clear()
    try:
        limited = await client.post("/api/v1/auth/login", json=body, headers=forwarded)
        assert limited.status_code == 429
    finally:
        monkeypatch.delenv("TRUST_PROXY_HEADERS")
        get_settings.cache_clear()


async def test_ai_provider_failure_is_a_gateway_error_not_a_500(client, app, seeded, auth_header):
    from app.application.ai.gateway import AIGateway
    from app.infrastructure.repositories import SqlAIRequestLog
    from tests.integration.test_risk_flow import FailingProvider

    app.state.gateway = AIGateway(
        FailingProvider(), SqlAIRequestLog(app.state.audit_session_factory), timeout_seconds=5.0
    )
    ops = await auth_header("ops@a.caremesh.org")
    await client.post(
        "/api/v1/knowledge/documents",
        json={
            "title": "Sleep and exam season",
            "source_name": "sleep",
            "content": "Sleep gets harder during exam season. Keep a wind down routine "
            "and write tomorrow's tasks down before bed.",
        },
        headers=ops,
    )
    patient = await auth_header("patient@a.caremesh.org")
    response = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "how do I sleep during exam season"},
        headers=patient,
    )
    assert response.status_code == 502
    assert response.json()["type"].endswith("ai_provider_error")
