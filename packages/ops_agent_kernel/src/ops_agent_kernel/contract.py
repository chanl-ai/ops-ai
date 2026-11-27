"""What the kernel needs from the agent loop library under it, in the kernel's own types.

The kernel runs a turn's tools, its approvals and its budget; the loop calls the model and the tools in turn. Only
`strands_loop/` imports a loop library; everything it is handed and hands back is defined here, so the kernel's
rules are the same whichever loop runs them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from ops_service_kit.http import Json

LoopName = Literal["pydantic_ai", "strands"]
LOOPS: tuple[LoopName, ...] = ("pydantic_ai", "strands")


@dataclass
class LoopChoice:
    """The loop a new turn runs on when its ports name none. A paused turn resumes on the loop that paused it."""

    default: LoopName = "pydantic_ai"


LOOP = LoopChoice()


@dataclass(frozen=True)
class CallContext:
    """What a tool body is told about its call: its id, the model step it was asked on (1 is the first request of
    the run), and whether a person approved it."""

    tool_call_id: str
    run_step: int
    tool_call_approved: bool = False


@dataclass(frozen=True)
class ModelEndpoint:
    """Where the loop sends model calls: an OpenAI-compatible client (models-service's gateway), the alias it asks
    for, the headers each call names (tenant, budget, replay key), computed in the kernel's task per call, and who is
    told each answered call's tokens and seconds (the run's step record), in the same task. A call `falls_back` refuses
    (its status and body) is sent once more to `fallback`, before anything of its answer is read."""

    client: Any
    model_id: str
    headers: Callable[[str], Awaitable[dict[str, str]]] | None = None
    answered: Callable[[int, int, float], None] | None = None
    fallback: ModelEndpoint | None = None
    falls_back: Callable[[int, object], bool] | None = None


@dataclass
class LoopTool:
    """One tool as the loop offers it. `offered` is asked before every model request; `gated` pauses the call for a
    person before it runs unless `barred` says it is refused anyway."""

    name: str
    description: str
    input_schema: Json
    call: Callable[[CallContext, Json], Awaitable[Any]]
    offered: Callable[[CallContext], Awaitable[bool]]
    gated: bool = False
    barred: Callable[[], str | None] = field(default=lambda: None)


class LoopPause(Exception):
    """Raised by a tool body: the call waits for a person (the gateway would not send it without one)."""

    def __init__(self, reason: str | None = None) -> None:
        super().__init__(reason or "approval needed")
        self.reason = reason


class StepLimitReached(Exception):
    """The run would make more model requests than its step limit allows."""


class SchemaMismatch(Exception):
    """The final answer did not match the turn's output schema, after one more try."""


class LoopRefused(Exception):
    """The model endpoint refused a call: its HTTP status and the body it sent."""

    def __init__(self, status: int, body: object) -> None:
        super().__init__(f"model call refused ({status})")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class StepStarted:
    step: int


@dataclass(frozen=True)
class TextChunk:
    text: str


@dataclass(frozen=True)
class ToolStarted:
    tool_call_id: str
    name: str
    arguments: Json


@dataclass(frozen=True)
class ToolEnded:
    tool_call_id: str
    ok: bool
    content: Any


@dataclass(frozen=True)
class LoopPaused:
    """The run stopped at a call waiting for a person. `state` is opaque outside the loop that wrote it."""

    tool_call_id: str
    name: str
    arguments: Json
    reason: str | None
    state: bytes
    messages: list[Json]


@dataclass(frozen=True)
class LoopDone:
    text: str
    messages: list[Json]
    input_tokens: int
    output_tokens: int
    requests: int


LoopEvent = StepStarted | TextChunk | ToolStarted | ToolEnded | LoopPaused | LoopDone
