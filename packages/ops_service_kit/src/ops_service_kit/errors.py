"""Errors the Runtime API turns into the console's envelope: `{success: false, error: {code, message, status}}`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict, Unpack


class ErrorOptions(TypedDict, total=False):
    """What an error may say besides its message: its own `code`, and `details` sent beside it, any mapping (a
    TypedDict passes)."""

    code: str | None
    details: Mapping[str, object] | None


class ApiError(Exception):
    status = 500
    code = "internal"

    # A dict of details is kept as passed, so a key added to it before the error is answered is still sent; another
    # mapping is copied into one.
    def __init__(self, message: str, **options: Unpack[ErrorOptions]) -> None:
        # `**options` takes any keyword at run time; one ErrorOptions does not name is refused, as a named parameter
        # list refuses it.
        if unknown := sorted(set(options) - ErrorOptions.__optional_keys__):
            raise TypeError(f"ApiError.__init__() got an unexpected keyword argument {unknown[0]!r}")
        super().__init__(message)
        self.message = message
        details = options.get("details")
        self.details: dict[str, Any] | None = details if details is None or isinstance(details, dict) else dict(details)
        if code := options.get("code"):
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
        # `what` names the missing thing ("Run", "Agent ag_1"); a caller that words the whole sentence ends it with a
        # full stop, and it is kept as written rather than read as "No item with that id. was not found."
        super().__init__(what if what.rstrip().endswith((".", "!", "?")) else f"{what} was not found.")


class Conflict(ApiError):
    status = 409
    code = "conflict"


class Unprocessable(ApiError):
    status = 422
    code = "unprocessable"


class TooLarge(ApiError):
    status = 413
    code = "too_large"


class TooManyRequests(ApiError):
    status = 429
    code = "too_many_requests"

    def __init__(
        self,
        message: str,
        *,
        retry_after_s: int | None = None,
        **options: Unpack[ErrorOptions],
    ) -> None:
        super().__init__(message, **options)
        # Sent as the Retry-After header, so a client waits the time the service named.
        self.retry_after_s = retry_after_s


class ServiceUnavailable(ApiError):
    status = 503
    code = "unavailable"


class StepUpRequired(ApiError):
    status = 422
    code = "step_up_required"
