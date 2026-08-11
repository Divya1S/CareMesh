from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
