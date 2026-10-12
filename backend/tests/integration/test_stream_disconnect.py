"""A client that drops a streaming reply mid way, against a real server.

httpx's ASGITransport runs the app to completion, so it cannot reproduce
what Starlette does on a real disconnect: cancel the response task through
an anyio cancel scope. This test runs uvicorn in process, closes the
connection after the first delta, and checks what the audit trail says.
"""

import asyncio
import socket

import httpx
import pytest
import uvicorn
from sqlalchemy import select

from app.application.ai.gateway import AIGateway
from app.application.ai.types import StreamDelta
from app.infrastructure.ai.fake_provider import FakeLLMProvider
from app.infrastructure.models import AIRequestRow, MessageRow
from app.infrastructure.repositories import SqlAIRequestLog

pytestmark = pytest.mark.integration


class SlowStreamProvider:
    """The fake provider, streamed one word every 50 ms so the client can
    leave in the middle."""

    name = "fake"
    model_name = "fake-sim-1"
    simulated = True

    def __init__(self) -> None:
        self._inner = FakeLLMProvider()

    async def complete(self, request):
        return await self._inner.complete(request)

    async def stream(self, request):
        response = await self._inner.complete(request)
        for word in response.text.split(" "):
            yield StreamDelta(word + " ")
            await asyncio.sleep(0.05)
        yield response


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_client_disconnect_is_audited_as_cancelled_on_a_real_server(app, seeded, login):
    app.state.gateway = AIGateway(
        SlowStreamProvider(), SqlAIRequestLog(app.state.audit_session_factory), timeout_seconds=5.0
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    serve = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started

        base = f"http://127.0.0.1:{port}"
        tokens = await login("patient@a.caremesh.org")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        async with httpx.AsyncClient(base_url=base, headers=headers) as client:
            conversation_id = (
                await client.post("/api/v1/conversations", json={"title": "t"})
            ).json()["id"]
            async with client.stream(
                "POST",
                f"/api/v1/conversations/{conversation_id}/messages/stream",
                json={"content": "I have been feeling sad"},
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith('data: {"type": "delta"'):
                        break
            # Leaving the context closes the connection mid stream.

        # Give the server a moment to observe the disconnect and audit it.
        row = None
        for _ in range(60):
            async with app.state.session_factory() as session:
                row = await session.scalar(
                    select(AIRequestRow)
                    .where(AIRequestRow.prompt_name == "dira_reply")
                    .order_by(AIRequestRow.id.desc())
                )
            if row is not None:
                break
            await asyncio.sleep(0.1)
        assert row is not None, "the gateway call must be audited even when the client leaves"
        assert row.status == "cancelled", row.status
        assert row.error_type == "ClientDisconnected"

        async with app.state.session_factory() as session:
            senders = [
                m.sender_type.value for m in (await session.scalars(select(MessageRow))).all()
            ]
        assert senders == ["patient"], "the patient message is durable; no partial reply"
    finally:
        server.should_exit = True
        await serve
