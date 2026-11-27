"""The loop kinds and the run trace on the wire: one source for the service, the SDKs and the console
(docs/design/agents-v2/automatic-mode-and-loop-kinds.md, "Interfaces"; api.md, the trace route)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import JsonValue

from .chat import ModeName, ModeStep, WireModel

__all__ = ["LoopKindOut", "ModeName", "ModeStep", "RunTrace", "TraceStep"]
Requirement = Literal["agents", "sandbox", "workflow", "rubric"]
StepKind = Literal["model", "tool", "mode", "plan", "agent_asked", "handoff", "interrupt", "guardrail"]


class LoopKindOut(WireModel):
    """One loop kind an agent can run, with its own settings as JSON Schema; the console draws the form from it."""

    kind: str
    name: str
    description: str
    when_to_use: str
    settings_schema: dict[str, JsonValue]
    requires: list[Requirement]
    # False when the install lacks what the kind requires, or the kind arrives in a later release.
    available: bool
    unavailable_reason: str | None = None


class TraceStep(WireModel):
    index: int
    kind: StepKind
    title: str
    started_at: str
    duration_ms: int | None = None
    status: str | None = None
    model: str | None = None
    tool: str | None = None
    call_id: str | None = None
    detail: dict[str, Any] | None = None


class RunTrace(WireModel):
    """One run's steps, read back from the thread's event log: what ran, in order, and the modes it used."""

    run_id: str
    thread_id: str
    agent_id: str | None = None
    loop: str | None = None
    modes: list[ModeStep]
    steps: list[TraceStep]
    stop_reason: str | None = None
