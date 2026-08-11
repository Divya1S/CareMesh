"""Correlation ID middleware and structured request logging."""

import re
import time

import structlog

from app.domain.ids import uuid7
from app.infrastructure.metrics import HTTP_DURATION, HTTP_REQUESTS, normalize_path

logger = structlog.get_logger()

# Client supplied request ids land in String(64) columns and in log lines,
# so anything oversized or with control characters gets replaced instead of
# truncating an insert or forging log entries.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class CorrelationIdMiddleware:
    """Binds a request id to log context and echoes it as X-Request-ID."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="replace")
        request_id = supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid7())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        # Exposed as request.state.request_id so use cases can carry it as a
        # correlation id into domain events.
        scope.setdefault("state", {})["request_id"] = request_id
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
            duration = time.perf_counter() - started
            path = normalize_path(scope["path"])
            HTTP_REQUESTS.labels(
                method=scope["method"], path=path, status=str(status_holder["status"])
            ).inc()
            HTTP_DURATION.labels(method=scope["method"], path=path).observe(duration)
            logger.info(
                "http_request",
                method=scope["method"],
                path=scope["path"],
                status=status_holder["status"],
                duration_ms=round(duration * 1000, 1),
            )
