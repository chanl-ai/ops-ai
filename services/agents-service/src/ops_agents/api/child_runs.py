"""Workflows as agent tools, API side (docs/architecture/workflows-as-tools.md): the `WorkflowRunner` port an agent
turn reaches through `GraphDeps.workflows`.

A call finds or creates the child thread keyed by the tool call's idempotency key (`external_key`), so a turn
retried after a crash meets the same child; runs it under the child's own lease, exactly as a route would; and
returns its result, or a handle when it stopped at a review, which Cases and Reviews then show like any workflow.
"""

from __future__ import annotations

import hashlib
from typing import Any, cast

from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import ToolGrant
from ops_agents.graphs.common import WORKFLOW_TOOL_PREFIX
from ops_service_kit.errors import ApiError, Conflict
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import get_logger

from ..store.events import EventLog
from ..store.leases import LeaseHeldError
from .deps import Runtime
from .runs import config, execute, graph_store, pending, resolve
from .workflow_registry import thread_pin

log = get_logger("ops_agents.api.child_runs")

# A definition's input is the email its nodes read (WorkflowState.email).
EMAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sender": {"type": "string", "description": "Who the email is from"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["sender", "subject", "body"],
}


async def tell_parent(rt: Runtime, child: dict[str, Any]) -> None:
    """A child an agent started has finished: its outcome goes on the parent thread as a `child_finished` event, which
    the conversation shows after the turn that started it. No model call; the person reads the outcome."""
    meta = cast(dict[str, Any], child.get("meta") or {})
    parent_id = meta.get("parentThreadId")
    parent = await graph_store(rt).thread(str(parent_id)) if parent_id else None
    if parent is None:
        return
    _, graph = await resolve(rt, child["id"])
    values: dict[str, Any] = (await graph.aget_state(config(child["id"]))).values or {}
    await EventLog(graph_store(rt).engine).append(
        thread_id=parent["id"],
        team_id=parent["team_id"],
        run_id=None,
        type_="child_finished",
        data={
            "childThreadId": child["id"],
            "workflow": child["graph"],
            "parentRunId": meta.get("parentRunId"),
            "outcome": values.get("status"),
        },
    )


class ChildRuns:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def _published(self, workflow: str) -> tuple[int, str] | None:
        """The registry's published version of `workflow` and its digest; None when it is not a registry workflow or is
        paused, deleted or never published."""
        try:
            version = await thread_pin(self.rt, workflow)
        except ApiError:
            return None
        stored = await graph_store(self.rt).version(workflow, version) if version is not None else None
        return (version, stored["digest"]) if version is not None and stored else None

    async def offers(self, granted: list[str]) -> list[ToolGrant]:
        out: list[ToolGrant] = []
        for name in granted:
            workflow = name.removeprefix("workflow:")
            if await self._published(workflow) is None:
                continue  # unpublished, paused or unknown: the agent is not offered it
            out.append(
                ToolGrant(
                    name=f"{WORKFLOW_TOOL_PREFIX}{workflow}",
                    server="workflows",
                    description=f"Start the {workflow.replace('_', ' ')} workflow on an email and return its outcome",
                    access="workflow",
                    input_schema=EMAIL_SCHEMA,
                )
            )
        return out

    async def run(
        self, *, workflow: str, arguments: dict[str, Any], key: str, parent_thread_id: str, parent_run_id: str | None
    ) -> ToolOutcome:
        store = graph_store(self.rt)
        pin = await self._published(workflow)
        if pin is None:
            return ToolOutcome(ok=False, output={"error": f"Workflow {workflow} is not published, so it cannot start."})
        parent = await store.thread(parent_thread_id)
        assert parent is not None, "a tool runs inside its parent's run"
        meta = {
            "startedBy": "agent",
            "agentName": cast(dict[str, Any], parent["meta"] or {}).get("agentName") or "an agent",
            "parentThreadId": parent_thread_id,
            "parentRunId": parent_run_id,
        }
        row, created = await store.find_or_create_thread(
            new_id("gth"),
            workflow,
            meta,
            parent["team_id"],
            now_iso(),
            external_key=f"tool:{key}",
            parent_thread_id=parent_thread_id,
            version=pin[0],
            digest=pin[1],
        )
        thread_id = row["id"]
        if created:
            await self._run(
                thread_id, {"email": arguments}, run_id="run_" + hashlib.sha256(key.encode()).hexdigest()[:16]
            )
        return await self._outcome(workflow, thread_id)

    async def _run(self, thread_id: str, graph_input: dict[str, Any], *, run_id: str) -> None:
        rt, store = self.rt, graph_store(self.rt)
        assert rt.leases is not None
        try:
            generation = await rt.leases.acquire(thread_id, run_id)
        except LeaseHeldError as e:
            raise Conflict("The workflow is already running.", code="run_active") from e
        if not await store.start_run(
            run_id, thread_id, "input", now_iso(), {"input": graph_input}, generation=generation
        ):
            await rt.leases.release(thread_id, run_id)
            return  # this child's run exists: a retried turn reads its outcome instead of starting it again
        await store.set_thread_status(thread_id, "busy", now_iso(), generation=generation)
        row, graph = await resolve(rt, thread_id)
        async for _ in execute(rt, row, graph, graph_input=graph_input, run_id=run_id, kind="input"):
            pass

    async def _outcome(self, workflow: str, thread_id: str) -> ToolOutcome:
        _, graph = await resolve(self.rt, thread_id)
        snap = await graph.aget_state(config(thread_id))
        values: dict[str, Any] = snap.values or {}
        base = {"workflow": workflow, "threadId": thread_id}
        if pending(snap):
            # Decided in Cases and Reviews like any workflow review; the parent does not wait for it.
            return ToolOutcome(ok=True, output=base | {"status": "waiting_review", "reviewId": thread_id})
        runs = await graph_store(self.rt).runs(thread_id)
        if runs and runs[-1]["status"] == "error":
            return ToolOutcome(ok=False, output=base | {"status": "failed"})
        return ToolOutcome(ok=True, output=base | {"status": "finished", "outcome": values.get("status")})
