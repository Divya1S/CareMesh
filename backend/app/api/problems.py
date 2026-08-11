"""Problem details error responses (RFC 9457 shape) for expected failures."""

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.errors import (
    AppError,
    ConflictError,
    DomainValidationError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
)

_STATUS_BY_ERROR: dict[type[AppError], int] = {
    UnauthorizedError: 401,
    ForbiddenError: 403,
    NotFoundError: 404,
    ConflictError: 409,
    DomainValidationError: 422,
    RateLimitedError: 429,
}

logger = structlog.get_logger()


def _problem(request: Request, status: int, code: str, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://caremesh.example/problems/{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": str(request.url.path),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status = _STATUS_BY_ERROR.get(type(exc), 500)
        response = _problem(request, status, exc.code, exc.title, exc.detail)
        if status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        if isinstance(exc, RateLimitedError):
            response.headers["Retry-After"] = str(exc.retry_after_seconds)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(
            request, 422, "request_validation", "Request validation failed", str(exc.errors())
        )

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        # Log the class only. Never the request body, which may hold clinical text.
        logger.error("unhandled_error", error_type=type(exc).__name__, path=request.url.path)
        return _problem(
            request, 500, "internal", "Internal server error", "An unexpected error occurred"
        )
