from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
