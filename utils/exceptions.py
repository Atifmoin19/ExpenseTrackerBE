"""Custom exception hierarchy. A single `app_error_handler` in main.py catches
AppError (and subclasses) and renders it through the standard response envelope
with the right HTTP status, so routers just `raise NotFoundError("...")` etc.
"""


class AppError(Exception):
    """Base application error — carries an error `code`, human `message`, and HTTP status."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ValidationError(AppError):
    def __init__(self, message: str = "Validation error") -> None:
        super().__init__("validation_error", message, 422)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__("unauthorized", message, 401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__("forbidden", message, 403)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__("not_found", message, 404)


class ConflictError(AppError):
    def __init__(self, message: str = "Conflict") -> None:
        super().__init__("conflict", message, 409)


class ServiceUnavailableError(AppError):
    def __init__(self, message: str = "Service unavailable") -> None:
        super().__init__("service_unavailable", message, 503)
