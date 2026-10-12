"""Application error types. The API layer maps these to problem details responses."""


class AppError(Exception):
    code = "app_error"
    title = "Application error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class UnauthorizedError(AppError):
    code = "unauthorized"
    title = "Unauthorized"


class ForbiddenError(AppError):
    code = "forbidden"
    title = "Forbidden"


class NotFoundError(AppError):
    code = "not_found"
    title = "Not found"


class ConflictError(AppError):
    code = "conflict"
    title = "Conflict"


class DomainValidationError(AppError):
    code = "validation_error"
    title = "Validation error"


class RateLimitedError(AppError):
    code = "rate_limited"
    title = "Too many requests"

    def __init__(self, detail: str, retry_after_seconds: int = 60) -> None:
        super().__init__(detail)
        self.retry_after_seconds = retry_after_seconds


class ServiceUnavailableError(AppError):
    """A dependency the request cannot do without is down (for example the
    rate limiter store behind login). Fail fast, say so, and ask the client
    to retry."""

    code = "service_unavailable"
    title = "Service unavailable"

    def __init__(self, detail: str, retry_after_seconds: int = 5) -> None:
        super().__init__(detail)
        self.retry_after_seconds = retry_after_seconds
