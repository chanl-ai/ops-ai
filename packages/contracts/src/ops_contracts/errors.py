"""One error model for every run, reply and call that fails: a kind, a stable code, a builder message, a sentence safe
for a customer and whether a retry helps (docs/architecture/workflow-runner.md, "One error model").

Five kinds. `input`: what was sent cannot run as it is. `refused`: a rule said no. `upstream`: an app, a tool or a model
provider failed. `timeout`: a clock ran out (`details.clock` says which). `internal`: our fault. A cancelled run has the
status Cancelled and carries no error.

`CODES` is the only table that says which kind a code is and whether trying again helps; the engine, the services, the
console, both SDKs and the CLI read it (the SDKs and the console through the `RunFailure` shape in the OpenAPI
documents), so no layer keeps a second list. How an HTTP status reads as a kind and the CLI's exit status per kind
belong to the SDKs (ops_ai.errors), which ship without this package. The HTTP error family in
`ops_service_kit.errors` stays the transport.
"""

from __future__ import annotations

from typing import Literal, NamedTuple, get_args

from pydantic import Field

from .chat import WireModel

# A detail is one plain value (`clock`, `end`, `reported`), so the record stays the same JSON in every language.
Detail = str | int | float | bool | None
ErrorKind = Literal["input", "refused", "upstream", "timeout", "internal"]
KINDS: tuple[ErrorKind, ...] = get_args(ErrorKind)


class Code(NamedTuple):
    kind: ErrorKind
    retryable: bool
    # One sentence an end user may read: no code, no trace, no step id.
    user_message: str


_TRY_AGAIN = "Something went wrong on our side. Please try again."
CODES: dict[str, Code] = {
    # input: fix the input or the definition.
    "input_invalid": Code("input", False, "The request could not be run as it was sent."),
    "schema_mismatch": Code("input", False, "The request did not have the shape this step needs."),
    "unknown_reference": Code("input", False, "The request named something that does not exist."),
    "missing_value": Code("input", False, "A value this step needs was missing."),
    # refused: a rule said no; only a full team or a missing sign-in is tried again (after the wait or the sign-in).
    "forbidden": Code("refused", False, "This is not allowed for your account."),
    "guardrail_blocked": Code("refused", False, "This was stopped by one of the team's rules."),
    "approval_rejected": Code("refused", False, "The change was not approved."),
    "budget_reached": Code("refused", False, "The team's budget for this ran out, so it stopped."),
    "app_not_set_up": Code("refused", False, "An app this step uses is not set up for this team yet."),
    # A person signs in or picks an account, then the same call runs.
    "sign_in_needed": Code("refused", True, "An app this step uses needs a sign-in first."),
    "team_at_capacity": Code("refused", True, "Your request is waiting for a free slot and will start shortly."),
    # The workflow reached an end its builder marked as a failure.
    "ended_as_failure": Code("refused", False, "This stopped where the workflow says to stop."),
    # upstream: an app, tool or model failed; the step's retry policy tries again, a retry-after wins.
    "tool_failed": Code("upstream", True, "An app this step uses returned an error. Please try again."),
    "app_unavailable": Code("upstream", True, "An app this step uses could not be reached. Please try again."),
    "app_timed_out": Code("upstream", True, "An app this step uses did not answer in time. Please try again."),
    "model_rate_limited": Code("upstream", True, "The assistant is busy right now. Please try again shortly."),
    "model_unavailable": Code("upstream", True, "The assistant could not be reached. Please try again."),
    # A write that may have happened: never sent again by a retry; a person checks the app first.
    "write_uncertain": Code("upstream", False, "A change may have been made. Please check before trying again."),
    # The codes a chat reply already ends with (models-service's refusals and the kernel's own), kept as they are sent.
    "rate_limited": Code("upstream", True, "The assistant is busy right now. Please try again shortly."),
    "key_budget_exhausted": Code("refused", False, "The assistant's budget is spent for now."),
    "sensitivity_not_cleared": Code("refused", False, "This assistant may not use data this sensitive."),
    "guardrail_unavailable": Code("upstream", True, "The assistant's safety checks could not run. Please try again."),
    "schema_error": Code("input", False, "The answer did not have the shape that was asked for."),
    # models-service's other refusals: a key or budget an admin fixes, a model no longer offered, a provider failing.
    "key_revoked": Code("refused", False, "The assistant's model key is no longer valid."),
    "key_expired": Code("refused", False, "The assistant's model key is no longer valid."),
    "key_not_registered": Code("refused", False, "The assistant has no model key yet."),
    "invalid_key": Code("refused", False, "The assistant's model key was not accepted."),
    "tenant_budget_exhausted": Code("refused", False, "The team's budget for the assistant is spent for now."),
    "images_not_cleared": Code("refused", False, "This assistant may not read images or files."),
    "provider_key_missing": Code("refused", False, "The assistant's model provider is not set up yet."),
    "provider_auth_failed": Code("refused", False, "The assistant's model provider refused its key."),
    "alias_not_found": Code("input", False, "The assistant's model is no longer offered."),
    "unknown_model_alias": Code("input", False, "The assistant's model is no longer offered."),
    "provider_bad_request": Code("input", False, "The assistant's model provider refused the request."),
    "provider_unreachable": Code("upstream", True, "The assistant could not be reached. Please try again."),
    "provider_rate_limited": Code("upstream", True, "The assistant is busy right now. Please try again shortly."),
    "provider_timeout": Code("upstream", True, "The assistant did not answer in time. Please try again."),
    "provider_error": Code("upstream", True, "The assistant could not answer. Please try again."),
    # timeout: which clock ran out is in details.clock.
    "queued_too_long": Code("timeout", False, "This waited too long to start, so it was stopped."),
    "step_too_long": Code("timeout", True, "A step took too long. Please try again."),
    "reply_too_long": Code("timeout", True, "The reply took too long. Please try again."),
    "nobody_answered": Code("timeout", False, "Nobody answered in time, so this stopped."),
    "heartbeat_lost": Code("timeout", True, _TRY_AGAIN),
    # internal: our fault; tried again by a redrive after a fix.
    "worker_crashed": Code("internal", False, _TRY_AGAIN),
    "stuck": Code("internal", False, _TRY_AGAIN),
    "internal_error": Code("internal", False, _TRY_AGAIN),
    # The HTTP error family's own codes (ops_service_kit.errors), so a refused call reads its kind from this table too.
    "validation_failed": Code("input", False, "The request could not be run as it was sent."),
    "not_found": Code("input", False, "The request named something that does not exist."),
    "conflict": Code("input", False, "This clashes with a change made since. Please reload and try again."),
    "too_large": Code("input", False, "What was sent is too large."),
    # A 422 from a rule ("a read may not call a write"), as the error family documents it.
    "unprocessable": Code("refused", False, "This is not allowed here."),
    # Tried again after the sign-in or the step-up, as `sign_in_needed` is.
    "unauthorized": Code("refused", True, "Please sign in again."),
    "step_up_required": Code("refused", True, "Please confirm it is you, then try again."),
    # Our own limit: the caller waits the Retry-After it names.
    "too_many_requests": Code("refused", True, "Too many requests right now. Please try again shortly."),
    "unavailable": Code("upstream", True, "A service this needs could not be reached. Please try again."),
    "internal": Code("internal", False, _TRY_AGAIN),
}


def code_of(code: str | None) -> Code:
    """The table row for `code`; an unknown code reads as `internal_error`, so no failure is ever left without one."""
    return CODES.get(code or "", CODES["internal_error"])


class FailedStep(WireModel):
    id: str
    name: str | None = None


class RunError(WireModel):
    """What failed, in one shape everywhere. `message` is for the builder; `user_message` is the only part an end user
    reads. `retry_after_seconds` is set when the caller should wait before trying again (a provider's retry-after, a
    full team)."""

    kind: ErrorKind
    code: str
    message: str
    user_message: str
    retryable: bool
    retry_after_seconds: float | None = None
    step: FailedStep | None = None
    attempt: int | None = None
    of: int | None = None
    trace_id: str | None = None
    details: dict[str, Detail] = Field(default_factory=dict)


def run_error(
    code: str,
    message: str,
    *,
    step: str | None = None,
    step_name: str | None = None,
    attempt: int | None = None,
    of: int | None = None,
    retry_after_seconds: float | None = None,
    trace_id: str | None = None,
    details: dict[str, Detail] | None = None,
) -> RunError:
    """A RunError for `code`, its kind, retryable and customer sentence from `CODES`; an unknown code becomes
    `internal_error` with the given code kept in `details.reported` for the builder."""
    known = code in CODES
    row = code_of(code)
    extra = dict(details or {})
    if not known:
        extra["reported"] = code
    return RunError(
        kind=row.kind,
        code=code if known else "internal_error",
        message=message,
        user_message=row.user_message,
        retryable=row.retryable,
        retry_after_seconds=retry_after_seconds,
        step=FailedStep(id=step, name=step_name) if step else None,
        attempt=attempt,
        of=of,
        trace_id=trace_id,
        details=extra,
    )
