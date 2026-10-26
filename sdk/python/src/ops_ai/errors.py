"""One error class per kind of refusal, each carrying the API's error code, message and request id, so a caller can
branch on the class and quote the request id to support."""

from __future__ import annotations

from typing import Any


class OpsError(Exception):
    def __init__(
        self, status: int, code: str, message: str, request_id: str | None = None, details: Any = None
    ) -> None:
        super().__init__(f"{status} {code}: {message}" + (f" (request {request_id})" if request_id else ""))
        self.status, self.code, self.message, self.request_id, self.details = status, code, message, request_id, details


class BadRequest(OpsError):
    """400 or 422: the input was refused, including `step_up_required` and `approval_token_required`."""


class Unauthorized(OpsError):
    """401: no key, or a key the platform does not know."""


class Forbidden(OpsError):
    """403: the key's person or team may not do this."""


class NotFound(OpsError):
    """404, which is also what a team that cannot see a record gets."""


class Conflict(OpsError):
    """409: the record's state does not allow it, such as a run already running or a task already decided."""


class RateLimited(OpsError):
    """429: over a budget or rate limit."""


class ServerError(OpsError):
    """5xx."""


_BY_STATUS: dict[int, type[OpsError]] = {
    400: BadRequest, 401: Unauthorized, 403: Forbidden, 404: NotFound, 409: Conflict, 422: BadRequest, 429: RateLimited
}  # fmt: skip


def error_for(status: int, error: dict[str, Any], request_id: str | None, text: str) -> OpsError:
    cls = _BY_STATUS.get(status) or (ServerError if status >= 500 else OpsError)
    return cls(
        status,
        str(error.get("code") or "error"),
        str(error.get("message") or text or "request refused"),
        error.get("requestId") or request_id,
        error.get("details"),
    )
