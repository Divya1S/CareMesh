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
from app.application.ai.gateway import AIGateway
from app.infrastructure.ai.embeddings import create_embedding_provider
from app.infrastructure.ai.factory import create_provider
from app.infrastructure.db import create_engine, create_session_factory
from app.infrastructure.gauges import run_gauge_refresher
from app.infrastructure.logging import configure_logging
from app.infrastructure.repositories import SqlAIRequestLog
from app.infrastructure.settings import Settings, get_settings


def configure_state(app: FastAPI, settings: Settings, database_url: str) -> None:
    """Builds the process wide objects once: two engines (request pool and
    a separate audit pool), the LLM provider, the embedding model, and the
    gateway. Shared by the lifespan and the test fixtures so both wire the
    app the same way."""
    engine = create_engine(
        database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
    )
    audit_engine = create_engine(
        database_url,
        pool_size=settings.audit_pool_size,
        max_overflow=settings.audit_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
    )
    app.state.engine = engine
    app.state.audit_engine = audit_engine
    app.state.session_factory = create_session_factory(engine)
    app.state.audit_session_factory = create_session_factory(audit_engine)
    # Providers are built once: the semantic embedder loads a model, and a
    # real LLM adapter keeps a pooled HTTP client.
    app.state.llm_provider = create_provider(settings.llm_provider)
    app.state.embedder = create_embedding_provider(settings.embedding_provider)
    app.state.gateway = AIGateway(
        app.state.llm_provider,
        SqlAIRequestLog(app.state.audit_session_factory),
        timeout_seconds=settings.ai_timeout_seconds,
    )


async def dispose_state(app: FastAPI) -> None:
    provider = getattr(app.state, "llm_provider", None)
    close = getattr(provider, "aclose", None)
    if close is not None:
        await close()
    await app.state.audit_engine.dispose()
    await app.state.engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    configure_state(app, settings, settings.database_url)
    # Bounded socket timeouts: a blackholed Redis must fail fast with an
    # error instead of hanging every login and chat request forever.
    app.state.redis = Redis.from_url(
        settings.redis_url, socket_connect_timeout=2.0, socket_timeout=2.0
    )
    gauge_task = asyncio.create_task(run_gauge_refresher(app.state.session_factory))
    yield
    gauge_task.cancel()
    await app.state.redis.aclose()
    await dispose_state(app)


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
