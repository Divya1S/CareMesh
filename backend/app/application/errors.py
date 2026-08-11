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
