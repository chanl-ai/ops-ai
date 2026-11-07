"""A failed tool call in words, before the model sees it: what happened, the next step, and whether to try again.

The tool port wraps the gateway's executor with `WordedTools`. A failed outcome keeps its code on the call record and
the call log (`output`); only what the model reads (`for_model`) becomes `{"error": {what, next, retryable}}`, so a
reply never echoes CONNECTION_NOT_LINKED or RATE_LIMITED. An outcome that already carries a line for the model (the
Connect card's, activities/gateway.py CARD_LINES) is left as it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, cast

from ops_agent_kernel.ports import ToolExecutor, ToolOutcome


@dataclass(frozen=True)
class Words:
    what: str
    next: str
    retryable: bool


_SIGN_IN_AGAIN = Words("{app} needs you to sign in again", "Sign in to {app} from My accounts, then ask again", True)
_UNREACHABLE = Words("{app} could not be reached", "Try again shortly; if it keeps happening, ask an admin", True)
_FAILED = Words("{app} returned an error", "Try again; if it keeps happening, ask an admin", True)
_NOT_SET_UP = Words("{app} is not set up for this team yet", "Ask an admin to set it up", False)
_TIMED_OUT = Words("{app} did not answer in time", "Try again shortly", True)
_NO_ACCESS = Words("You do not have access to this in {app}", "Ask an admin for access", False)
_BAD_INPUT = Words("{app} did not accept the request as it was asked", "Try again with different values", True)
_LOST = Words("The answer from {app} was lost", "Check {app} before trying again", False)
_NOT_FOUND = Words("{app} has nothing by that name or id", "Check the name or id and ask again", True)

# By the gateway's and the tools' refusal codes (tools-service); codes are compared in capitals.
WORDS: dict[str, Words] = {
    "CONNECTION_NOT_LINKED": Words("{app} needs your sign-in", "Press Connect on the card shown, then ask again", True),
    "NOT_SIGNED_IN": _SIGN_IN_AGAIN,
    "SIGN_IN_NOT_FOUND": _SIGN_IN_AGAIN,
    "SIGN_IN_REFUSED": _SIGN_IN_AGAIN,
    "AUTH_EXPIRED": _SIGN_IN_AGAIN,
    "CONNECTION_REVOKED": _SIGN_IN_AGAIN,
    "AUTH_FAILED": Words("{app} did not accept the sign-in", "Ask an admin to check the app's sign-in", False),
    "RATE_LIMITED": Words("{app} is busy and asked for fewer calls", "Try again in a minute", True),
    "FORBIDDEN": _NO_ACCESS,
    "CONNECTION_OUT_OF_SCOPE": _NO_ACCESS,
    "NOT_FOUND": _NOT_FOUND,
    "ACCOUNT_NOT_FOUND": _NOT_FOUND,
    "TIMEOUT": _TIMED_OUT,
    "UPSTREAM_TIMEOUT": _TIMED_OUT,
    "CONNECT_TIMEOUT": _TIMED_OUT,
    "POOL_TIMEOUT": _TIMED_OUT,
    "UPSTREAM_UNREACHABLE": _UNREACHABLE,
    "CONNECT_FAILED": _UNREACHABLE,
    "TLS_FAILED": _UNREACHABLE,
    "UPSTREAM_ERROR": _FAILED,
    "UPSTREAM_STATUS": _FAILED,
    "PLUGIN_FAILED": _FAILED,
    "TOOL_ERROR": _FAILED,
    "CALL_FAILED": _FAILED,
    "ANSWER_UNREADABLE": Words("{app} answered in a form that could not be read", "Try again; then ask an admin", True),
    "EGRESS_DENIED": Words("This install may not reach {app}'s address", "Ask an admin to allow it", False),
    "CONNECTION_HOST_MISMATCH": Words("This install may not reach {app}'s address", "Ask an admin to allow it", False),
    "INVALID_INPUT": _BAD_INPUT,
    "INVALID_ARGUMENTS": _BAD_INPUT,
    "CONNECTION_NOT_SET": _NOT_SET_UP,
    "CONNECTION_MISSING": _NOT_SET_UP,
    "SECRET_MISSING": _NOT_SET_UP,
    "SECRET_UNAVAILABLE": _NOT_SET_UP,
    "PLUGIN_DISABLED": _NOT_SET_UP,
    "TOOL_NOT_ADDED": _NOT_SET_UP,
    "WRITE_IN_PROGRESS": Words("The same change is already running in {app}", "Wait a moment, then check", True),
    "CALL_LOST": _LOST,
    "CALL_ABANDONED": _LOST,
}
UNKNOWN = Words("The call to {app} failed", "Try again or ask an admin", True)
# The platform's own reads, named as the console names their areas.
APPS = {"search_knowledge": "the knowledge bases", "read_file": "Files", "read_document": "Documents"}
# A code the person must never read: upper case joined by underscores. A field name (account_id) is kept, so the model
# can fix the argument it names.
_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


def _object(value: Any) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _error(output: Any) -> dict[str, Any]:
    """The innermost error object of a failed outcome: the gateway's envelope may nest it once more."""
    err = _object((_object(output) or {}).get("error")) or {}
    return _object(err.get("error")) or err


def app_name(tool: str, details: dict[str, Any]) -> str:
    named = details.get("app") or details.get("appName") or details.get("connection")
    if named:
        return str(named)
    if tool in APPS:
        return APPS[tool]
    # A plugin tool is named after its app first (salesforce_query).
    return tool.split("_", 1)[0].capitalize() if "_" in tool else tool.capitalize()


def plain(text: str) -> str | None:
    """`text` when a person could read it as it is: no code in it; None otherwise."""
    text = text.strip()
    return text if text and _CODE.search(text) is None else None


def _said(output: Any) -> str | None:
    """The failure as text, when the outcome is a sentence rather than an error object."""
    if isinstance(output, str):
        return output
    inner = (_object(output) or {}).get("error")
    return inner if isinstance(inner, str) else None


def worded(tool: str, output: Any) -> dict[str, Any] | None:
    """What the model reads for a failed call of `tool`: `{what, next, retryable}`, plus the service's own message
    under `detail` when it has no code in it (an invalid input names the field to fix). None when the failure is
    already plain words ("The team has no file named …"), which the model reads as it is."""
    err = _error(output)
    code = str(err.get("code") or "").upper()
    if not code:
        text = _said(output) if not err else str(err.get("message") or "")
        if text and plain(text):
            return None
        code = next((m.group(0) for m in _CODE.finditer(text or "") if m.group(0) in WORDS), "")
    words = WORDS.get(code, UNKNOWN)
    app = app_name(tool, _object(err.get("details")) or {})
    out: dict[str, Any] = {
        "what": words.what.format(app=app),
        "next": words.next.format(app=app),
        "retryable": words.retryable,
    }
    message = err.get("message") if err else (output if isinstance(output, str) else None)
    if isinstance(message, str) and (said := plain(message)):
        out["detail"] = said
    return out


@dataclass(frozen=True)
class WordedTools:
    """The kernel's tool port with every failed call put into words for the model; `inner` runs the call."""

    inner: ToolExecutor

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        outcome = await self.inner.execute(tool, arguments, key=key, approval_token=approval_token)
        if outcome.ok or outcome.needs_review is not None or outcome.for_model is not None:
            return outcome
        words = worded(tool, outcome.output)
        return outcome if words is None else replace(outcome, for_model=words)
