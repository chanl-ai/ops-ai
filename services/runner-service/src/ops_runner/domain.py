"""What a run is: its limits, its result, and the answer the host gives each `ops.call`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MEMORY_MB = 256
DEFAULT_TIME_S = 10.0
DEFAULT_CALLS = 20


@dataclass(frozen=True)
class Limits:
    memory_mb: int = DEFAULT_MEMORY_MB
    time_s: float = DEFAULT_TIME_S
    calls: int = DEFAULT_CALLS


@dataclass
class RunResult:
    ok: bool
    output: Any = None
    error: dict[str, str] | None = None
    log: str = ""
    calls: int = 0
    create_ms: int = 0
    execute_ms: int = 0
    # One entry per `ops.call`: the tool, whether it answered, and its error code when it did not.
    trace: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def wire(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "log": self.log,
            "calls": self.calls,
            "createMs": self.create_ms,
            "executeMs": self.execute_ms,
            "trace": self.trace,
        }


# One `ops.call` from the guest: (tool, args) to {"ok": True, "output": ...} or {"ok": False, "error": {code, message}}.
CallAnswer = Callable[[str, dict[str, Any]], dict[str, Any]]


def failure(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
