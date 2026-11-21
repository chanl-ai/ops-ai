"""Errors the Runtime API turns into the console's envelope: `{success: false, error: {code, message, status, kind,
retryable}}`, the kind and retryable read from the one error model (ops_contracts.errors.CODES)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict, Unpack

from ops_contracts.errors import CODES, Code, code_of


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

    @property
    def row(self) -> Code:
        """The error model's row for this error. A specific code the table does not name (`approval_token_required`)
        takes the row of its class's code, and a class of a service's own (`ModelsUnavailable`) the row its status has
        in this family, so a refusal never reads as our fault."""
        classes = type(self).__mro__[: type(self).__mro__.index(ApiError)]
        family = [c.__dict__["code"] for c in classes if "code" in c.__dict__]
        known = next((c for c in (self.code, *family) if c in CODES), None)
        return CODES[known] if known else row_for_status(self.status)


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


# The family in the order a status is matched: the first class with a status names its row (422 reads as Unprocessable,
# a rule's refusal, before StepUpRequired).
_FAMILY: tuple[type[ApiError], ...] = (
    ValidationFailed,
    Unauthorized,
    Forbidden,
    NotFound,
    Conflict,
    Unprocessable,
    TooLarge,
    TooManyRequests,
    ServiceUnavailable,
    StepUpRequired,
)


def row_for_status(status: int) -> Code:
    """The row of the family's class for `status`; another 4xx is an input that cannot run, a 502 or 504 a service we
    call that failed, anything else our fault."""
    named = next((c for c in _FAMILY if c.status == status), None)
    if named:
        return CODES[named.code]
    if status in (502, 504):
        return CODES[ServiceUnavailable.code]
    return CODES["validation_failed"] if 400 <= status < 500 else code_of(None)


def error_row(status: int, code: str) -> Code:
    """The row for an error body built from a status and a code: the code's own, else its status's."""
    return CODES.get(code) or row_for_status(status)
