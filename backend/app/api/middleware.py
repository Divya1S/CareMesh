"""Correlation ID middleware and structured request logging."""

import time

import structlog

from app.domain.ids import uuid7

logger = structlog.get_logger()


class CorrelationIdMiddleware:
    """Binds a request id to log context and echoes it as X-Request-ID."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        request_id = headers.get(b"x-request-id", b"").decode() or str(uuid7())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_holder = {"status": 0}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "http_request",
                method=scope["method"],
                path=scope["path"],
                status=status_holder["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
