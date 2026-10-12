import hmac

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.application.errors import UnauthorizedError
from app.infrastructure.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request, response: Response) -> dict:
    """Liveness plus a readiness summary. The database is required (503
    without it); Redis is reported but not required, because the AI rate
    limiter fails open and only login depends on it."""
    status: dict = {"status": "ok", "database": "ok", "redis": "ok"}
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        status["status"] = "unavailable"
        status["database"] = "unavailable"
        response.status_code = 503
    try:
        await request.app.state.redis.ping()
    except Exception:
        status["redis"] = "unavailable"
        status["status"] = "degraded" if status["status"] == "ok" else status["status"]
    return status


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request) -> Response:
    # Open by default for local Prometheus. When METRICS_TOKEN is set the
    # scraper must present it, so a deployment can expose the port safely.
    token = get_settings().metrics_token
    if token:
        presented = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(presented.encode(), token.encode()):
            raise UnauthorizedError("Metrics require the scrape token")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
