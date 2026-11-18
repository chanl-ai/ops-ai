"""What a run is: its limits, its result, and the answer the host gives each `ops.call`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NotRequired, TypedDict

from ops_service_kit.http import JsonValue

DEFAULT_MEMORY_MB = 256
DEFAULT_TIME_S = 10.0
DEFAULT_CALLS = 20


@dataclass(frozen=True)
class Limits:
    memory_mb: int = DEFAULT_MEMORY_MB
    time_s: float = DEFAULT_TIME_S
    calls: int = DEFAULT_CALLS


class Failure(TypedDict):
    code: str
    message: str


class CallReply(TypedDict):
    """The host's answer to one `ops.call`, written back to the guest as one line."""

    ok: bool
    output: NotRequired[JsonValue]
    error: NotRequired[Failure | None]


class Trace(TypedDict):
    """One `ops.call`: the tool, whether it answered, and its error code when it did not."""

    tool: str
    ok: bool
    code: str | None


@dataclass
class RunResult:
    ok: bool
    output: JsonValue = None
    error: Failure | None = None
    log: str = ""
    calls: int = 0
    create_ms: int = 0
    execute_ms: int = 0
    trace: list[Trace] = field(default_factory=list[Trace])


# One `ops.call` from the guest: (tool, args) to {"ok": True, "output": ...} or {"ok": False, "error": {code, message}}.
CallAnswer = Callable[[str, dict[str, JsonValue]], CallReply]


def failure(code: str, message: str) -> Failure:
    return {"code": code, "message": message}
