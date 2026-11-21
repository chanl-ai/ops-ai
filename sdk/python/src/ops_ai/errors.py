"""One error class per kind of refusal, each carrying the API's error code, message and request id, so a caller can
branch on the class and quote the request id to support."""

from __future__ import annotations

from typing import Any, Literal

from ._generated.codes import CODES

# The one error model's kinds (the agents service's RunFailure): what failed, so a caller knows whose move it is.
Kind = Literal["input", "refused", "upstream", "timeout", "internal"]
# The CLI's exit status per kind; 1 stays "the command itself failed" (a bad flag, no key).
EXIT_CODES: dict[str, int] = {"input": 2, "refused": 3, "upstream": 4, "timeout": 5, "internal": 6}


class OpsError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        request_id: str | None = None,
        details: Any = None,
        *,
        kind: Kind | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(f"{status} {code}: {message}" + (f" (request {request_id})" if request_id else ""))
        self.status, self.code, self.message, self.request_id, self.details = status, code, message, request_id, details
        # The code's row in the one error model's table wins; then what the body says; the status only when neither.
        row = CODES.get(code)
        self.kind: Kind = row["kind"] if row else kind or kind_of_status(status)
        self.retryable: bool = (
            bool(row["retryable"]) if row else retryable if retryable is not None else status in RETRYABLE_STATUSES
        )


# Only when a refusal carries no code the table knows: a status that a later try can pass.
RETRYABLE_STATUSES = frozenset({408, 429, 502, 503, 504})


def kind_of_status(status: int) -> Kind:
    if status in (400, 404, 413, 422):
        return "input"
    if status in (401, 403, 409, 429):
        return "refused"
    if status in (408, 504):
        return "timeout"
    return "upstream" if status in (502, 503) else "internal"


class RunFailed(Exception):
    """A run that failed, raised by `runs.wait(check=True)`: the run's `failure` in the one error model. `message` is
    for the builder, `user_message` is safe to show an end user, `retryable` says whether trying again can help."""

    def __init__(self, run: dict[str, Any]) -> None:
        f: dict[str, Any] = run.get("failure") or {}
        self.run = run
        self.run_id = str(run.get("id") or "")
        self.kind: Kind = f.get("kind") or "internal"
        self.code = str(f.get("code") or "internal_error")
        self.message = str(f.get("message") or run.get("error") or "The run failed.")
        self.user_message = str(f.get("userMessage") or "")
        self.retryable = bool(f.get("retryable"))
        self.retry_after: float | None = f.get("retryAfterSeconds")
        self.trace_id: str | None = f.get("traceId")
        self.step: str | None = f.get("nodeName") or f.get("nodeId")
        self.attempt: int | None = f.get("attempt")
        self.of: int | None = f.get("of")
        # Plain values beside the code: which clock ran out, which End the run reached.
        self.details: dict[str, Any] = dict(f.get("details") or {})
        super().__init__(self.line())

    def line(self) -> str:
        """`failed · upstream/tool_failed at "Find customer" · attempt 3 of 3 · retryable · trace 4f2c…`"""
        parts = [f"failed · {self.kind}/{self.code}" + (f' at "{self.step}"' if self.step else "")]
        if self.attempt:
            parts.append(f"attempt {self.attempt} of {self.of}" if self.of else f"attempt {self.attempt}")
        parts.append("retryable" if self.retryable else "not retryable")
        if self.trace_id:
            parts.append(f"trace {self.trace_id}")
        return " · ".join(parts) + f": {self.message}"


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
        kind=error.get("kind"),
        retryable=error.get("retryable"),
    )
