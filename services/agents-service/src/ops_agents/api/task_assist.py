"""Task assist (c-302): when a typed review step pauses in a team that turned taskAssist on, one prompt-only model
call over what the task shows (its bound regions, never the run's state) writes the question in plain words, a
summary, the doubtful fields and a suggested action with its reason. It is written once and kept by step id; it never
decides, and a suggestion naming an action the type does not have is dropped when the task is read. A failed or slow
call leaves the task without an assist: the step pauses as before."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from ops_access import team_on
from ops_engine.ports import PromptPort, PromptRequest
from ops_service_kit.logging import get_logger

from .. import task_types as tt
from ..store.engine import AsyncEngine
from ..store.task_assists import TaskAssistStore
from ..store.task_types import TaskTypeNotFound
from ..store.tenancy import NoTenantError
from .engine_agents import KernelAgents, KernelPrompts
from .platform_policies import PolicySource, PolicyUnread
from .task_type_seeds import seeded_store

log = get_logger("ops_agents.task_assist")

KEY = "taskAssist"
# A pause waits at most this long for the assist; past it the task opens without one.
TIMEOUT_SECONDS = 20.0
# What a step's assist row holds while the model call runs, and after it failed.
PENDING: dict[str, Any] = {"pending": True}
FAILED: dict[str, Any] = {"failed": True}
# Past this a pending assist is never filled (its call times out at TIMEOUT_SECONDS, and a worker killed mid-call fills
# nothing), so it reads as failed and the console stops waiting for it (tick 32).
PENDING_LIMIT = timedelta(seconds=TIMEOUT_SECONDS * 3)


def settled(written: tuple[dict[str, Any], str] | None, now: datetime) -> dict[str, Any] | None:
    """The assist as a task shows it: a pending one older than PENDING_LIMIT as failed."""
    if written is None:
        return None
    assist, at = written
    if assist.get("pending") and datetime.fromisoformat(at.replace("Z", "+00:00")) < now - PENDING_LIMIT:
        return FAILED
    return assist


SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["question", "summary", "doubtful", "suggestion"],
    "properties": {
        "question": {"type": "string"},
        "summary": {"type": "string"},
        "doubtful": {"type": "array", "items": {"type": "string"}},
        "suggestion": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "reason"],
            "properties": {"action": {"type": "string"}, "reason": {"type": "string"}},
        },
    },
}


def instructions(actions: list[dict[str, Any]]) -> str:
    names = "\n".join(f"- {a['name']}: {a['label']}: {a.get('consequence') or ''}" for a in actions)
    return (
        "You help a person decide a task. From the task below, write: the one question the person answers, in plain "
        "words; a summary of the evidence in at most 60 words; the keys of the fields that look doubtful (empty when "
        "none); and the action you would suggest, by its name, with the reason in one sentence. The person decides, "
        f"not you.\n\nActions:\n{names}"
    )


@dataclass
class TaskAssist:
    db: AsyncEngine
    prompts: PromptPort
    policies: PolicySource

    async def on(self, team: str) -> bool:
        try:
            found = await self.policies.value(KEY)
        except (NoTenantError, PolicyUnread):
            return False
        return team_on(found, team)

    async def start(self, team: str, payload: dict[str, Any]) -> PromptRequest | None:
        """At a typed step's pause, with no model call: records the step's assist as pending and returns the call that
        writes it; None for an untyped step, with the setting off, or when the step already has one."""
        ref = cast(dict[str, Any] | None, payload.get("taskType"))
        step_id = str(payload.get("step_id") or "")
        if not ref or not step_id or not await self.on(team):
            return None
        try:
            _, record = await (await seeded_store(self.db)).published(
                str(ref["id"]), cast(int | None, ref.get("version"))
            )
        except TaskTypeNotFound:
            return None
        if not await TaskAssistStore(self.db).put(step_id, PENDING):
            return None
        bound = tt.bind(record, cast(dict[str, Any] | None, payload.get("params")) or {})
        return PromptRequest(
            instructions=instructions(bound["actions"]),
            message=json.dumps(bound["regions"], ensure_ascii=False, sort_keys=True, default=str),
            turn_id=f"assist:{step_id}",
            output_schema=SCHEMA,
        )

    async def finish(self, step_id: str, request: PromptRequest) -> None:
        """The model call `start` returned, written over the pending marker; a failure is recorded so the task stops
        showing the assist as on its way."""
        store = TaskAssistStore(self.db)
        try:
            result = await asyncio.wait_for(self.prompts.prompt(request), TIMEOUT_SECONDS)
        except Exception as e:
            log.warning("task_assist_failed", step=step_id, error=type(e).__name__)
            await store.fill(step_id, FAILED)
            return
        output: Any = result.output
        if result.ok and isinstance(output, dict):
            await store.fill(step_id, cast(dict[str, Any], output))
        else:
            log.warning("task_assist_unanswered", step=step_id, code=result.code)
            await store.fill(step_id, FAILED)

    async def write(self, team: str, payload: dict[str, Any]) -> None:
        """Both halves at once, for a caller that waits for the assist."""
        if (request := await self.start(team, payload)) is not None:
            await self.finish(str(payload["step_id"]), request)


def kernel_assist(db: AsyncEngine, agents: KernelAgents, policies: PolicySource) -> TaskAssist:
    """Task assist on the worker's model, gated by its own taskAssist setting alone. It is not an AI step, so the AI
    step rules (aiSteps for a run's team) are not its gate, and the assist call names no run they could read."""
    return TaskAssist(db, KernelPrompts(agents.ports, agents.model_alias), policies)


def region(assist: dict[str, Any] | None, actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The assist as the task's `assist` region, marked as AI; a suggestion of an action the type lacks is dropped."""
    if not assist or assist.get("failed"):
        return None
    if assist.get("pending"):
        # On its way: the console shows that and reads the task again until the assist is written.
        return {"region": "assist", "collapsed": False, "data": {"pending": True, "ai": True}}
    names = {str(a["name"]) for a in actions}
    suggestion = cast(dict[str, Any] | None, assist.get("suggestion"))
    if suggestion is not None and str(suggestion.get("action")) not in names:
        suggestion = None
    data = {**assist, "suggestion": suggestion, "ai": True}
    return {"region": "assist", "collapsed": False, "data": data}
