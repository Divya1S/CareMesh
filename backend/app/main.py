"""FastAPI app factory. Route handlers stay thin; logic lives in the application layer."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.middleware import CorrelationIdMiddleware
from app.api.problems import register_exception_handlers
from app.api.routes import (
    appointments,
    auth,
    claims,
    conversations,
    guardian,
    health,
    knowledge,
    ops,
    reviews,
    school,
)
from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.gauges import run_gauge_refresher
from app.infrastructure.logging import configure_logging
from app.infrastructure.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    engine = create_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis = Redis.from_url(settings.redis_url)
    gauge_task = asyncio.create_task(run_gauge_refresher(app.state.session_factory))
    yield
    gauge_task.cancel()
    await app.state.redis.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CareMesh AI (portfolio simulation)",
        description=(
            "Portfolio project simulating an AI native youth mental health platform. "
            "Not a real healthcare product. Not HIPAA compliant. Not for real patients."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(conversations.router, prefix="/api/v1")
    app.include_router(reviews.router, prefix="/api/v1")
    app.include_router(ops.router, prefix="/api/v1")
    app.include_router(knowledge.router, prefix="/api/v1")
    app.include_router(school.router, prefix="/api/v1")
    app.include_router(guardian.router, prefix="/api/v1")
    app.include_router(claims.router, prefix="/api/v1")
    app.include_router(appointments.router, prefix="/api/v1")
    return app


app = create_app()
