"""Async SQLAlchemy engine and session factory."""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def create_engine(
    database_url: str,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
    pool_timeout: float | None = None,
) -> AsyncEngine:
    """One engine per pool. Callers that must never wait on the request
    pool (the audit and AI request logs) create their own small engine."""
    options: dict = {"pool_pre_ping": True}
    if pool_size is not None:
        options["pool_size"] = pool_size
    if max_overflow is not None:
        options["max_overflow"] = max_overflow
    if pool_timeout is not None:
        options["pool_timeout"] = pool_timeout
    return create_async_engine(database_url, **options)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
