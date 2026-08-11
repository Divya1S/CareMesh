"""Structured logging setup. No message content, tokens, or PII in logs, ever."""

import logging

import structlog


def configure_logging(level: str, log_json: bool) -> None:
    renderer = structlog.processors.JSONRenderer() if log_json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
