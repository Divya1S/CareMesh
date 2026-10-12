"""The audit and AI request logs must never wait on the request pool.

A request holds one connection for its whole transaction. If the log
writer borrowed a second connection from the same pool, N concurrent
requests on a pool of N would each wait for a connection none of them
will release: a self deadlock that ends in pool timeouts. The logs get
their own engine, and this test pins both the failure mode and the fix.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.application.ai.types import AI_STATUS, AIRequestLogEntry
from app.domain.ids import uuid7
from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.repositories import SqlAIRequestLog
from tests.conftest import TEST_DB_URL

pytestmark = pytest.mark.integration


def _entry(org_id) -> AIRequestLogEntry:
    return AIRequestLogEntry(
        id=str(uuid7()),
        organization_id=str(org_id),
        provider="fake",
        model="fake-sim-1",
        prompt_name="dira_reply",
        prompt_version=1,
        status=AI_STATUS.ok,
        simulated=True,
        validation_ok=None,
        latency_ms=1.0,
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        correlation_id=None,
        error_type=None,
    )


async def test_log_write_does_not_wait_on_the_request_pool(seeded):
    request_engine = create_engine(TEST_DB_URL, pool_size=1, max_overflow=0, pool_timeout=1.0)
    audit_engine = create_engine(TEST_DB_URL, pool_size=1, max_overflow=0, pool_timeout=1.0)
    try:
        request_factory = create_session_factory(request_engine)
        async with request_factory() as request_session:
            # The request's transaction holds the only connection in its pool.
            await request_session.execute(text("SELECT 1"))

            # Same pool: the log writer waits for a connection that the
            # request will not release until it commits. Pool timeout.
            with pytest.raises(PoolTimeoutError):
                await SqlAIRequestLog(request_factory)._persist(_entry(seeded["org_a"].id))

            # Own pool: the write lands while the request is still open.
            await SqlAIRequestLog(create_session_factory(audit_engine))._persist(
                _entry(seeded["org_a"].id)
            )
    finally:
        await request_engine.dispose()
        await audit_engine.dispose()
