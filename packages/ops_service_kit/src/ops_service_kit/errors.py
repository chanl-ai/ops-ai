"""Errors the Runtime API turns into the console's envelope: `{success: false, error: {code, message, status}}`."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status = 500
    code = "internal"

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class ValidationFailed(ApiError):
    status = 400
    code = "validation_failed"


class Unauthorized(ApiError):
    status = 401
    code = "unauthorized"


class Forbidden(ApiError):
    status = 403
    code = "forbidden"


class NotFound(ApiError):
    status = 404
    code = "not_found"

    def __init__(self, what: str) -> None:
        super().__init__(f"{what} was not found.")


class Conflict(ApiError):
    status = 409
    code = "conflict"


class Unprocessable(ApiError):
    status = 422
    code = "unprocessable"


class TooManyRequests(ApiError):
    status = 429
    code = "too_many_requests"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        retry_after_s: int | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)
        # Sent as the Retry-After header, so a client waits the time the service named.
        self.retry_after_s = retry_after_s


class ServiceUnavailable(ApiError):
    status = 503
    code = "unavailable"


class StepUpRequired(ApiError):
    status = 422
    code = "step_up_required"
