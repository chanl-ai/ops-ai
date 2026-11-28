"""A run's trace, read back from the thread's event log: the steps the run took, in the order they were written, and
the modes its turns used (automatic-mode-and-loop-kinds.md, "Data model"). Nothing here is stored twice: a mode step
is the `mode` event the kernel's `ModeChanged` was emitted as, so the trace and the stream cannot disagree.
"""

from __future__ import annotations

from typing import Any

from ops_contracts.loops import ModeStep, RunTrace, TraceStep
from ops_service_kit.http import Json
from ops_service_kit.narrow import json_object

from ..store.events import EventOut


def _data(e: EventOut) -> Json:
    return json_object(e.data)


def trace_of(thread_id: str, run_id: str, events: list[EventOut], *, agent_id: str | None = None) -> RunTrace:
    steps: list[TraceStep] = []
    modes: list[ModeStep] = []
    stop: str | None = None

    def add(kind: Any, title: str, e: EventOut, **fields: Any) -> None:
        steps.append(TraceStep(index=len(steps), kind=kind, title=title, started_at=e.at, **fields))

    for e in events:
        d = _data(e)
        if e.type == "mode":
            step = ModeStep.model_validate(d)
            modes.append(step)
            add("mode", step.mode, e, detail={"reason": step.reason, "fixed": step.fixed})
        elif e.type == "plan":
            add(
                "plan",
                str(d.get("title") or "Plan"),
                e,
                detail={"steps": d.get("steps"), "revision": d.get("revision")},
            )
        elif e.type == "tool_call" and d.get("status") != "running":
            tool = str(d.get("tool") or "")
            add(
                "tool", tool, e, tool=tool, call_id=d.get("id"), status=d.get("status"), duration_ms=d.get("durationMs")
            )
        elif e.type in ("waiting", "waiting_review"):
            add("interrupt", "Waiting for a person", e, status="waiting")
        elif e.type == "turn":
            stop = str(d.get("stopReason") or "") or None
            add("model", str(d.get("model") or "model"), e, model=d.get("model"), status=d.get("status"))
    return RunTrace(run_id=run_id, thread_id=thread_id, agent_id=agent_id, modes=modes, steps=steps, stop_reason=stop)
