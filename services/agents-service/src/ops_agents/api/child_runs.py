"""Workflows as agent tools, API side (docs/architecture/workflows-as-tools.md): the `WorkflowRunner` port an agent
turn reaches through `GraphDeps.workflows`.

A call finds or creates the child thread keyed by the tool call's idempotency key (`external_key`), so a turn
retried after a crash meets the same child; runs it under the child's own lease, exactly as a route would; and
returns its result, or a handle when it stopped at a review, which Cases and Reviews then show like any workflow.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, cast

from ops_access import can
from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import ToolGrant
from ops_agents.graphs.common import WORKFLOW_TOOL_PREFIX
from ops_engine.store import TERMINAL, DefinitionStore, RunStore
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound, ValidationFailed
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import get_logger

from ..store.engine import DatabaseError, EngineTransactions
from ..store.events import EventLog
from ..store.leases import LeaseHeldError
from ..store.tenancy import NoTenantError, current_team
from .auth import Principal, caller_of
from .deps import Runtime
from .engine_runs import start_run
from .runs import as_thread_team, config, execute, graph_store, pending, require_graphs, resolve
from .workflow_registry import registry, thread_pin

log = get_logger("ops_agents.api.child_runs")

# The person a chat turn runs for (c-149). A workflow an agent holds as a tool is offered and started only when that
# person may start it: the turn's authority is the person's rights and the agent's grants together. A run with no person
# (an unattended agent run) acts as the agent; a chat turn whose person is not known (a turn resumed after a decision)
# starts no workflow.
TURN_PERSON: ContextVar[Principal | None] = ContextVar("ops_turn_person", default=None)


@contextmanager
def acting_for(person: Principal) -> Generator[None]:
    token = TURN_PERSON.set(person)
    try:
        yield
    finally:
        TURN_PERSON.reset(token)


def _parent_meta_from_config() -> dict[str, Any] | None:
    try:
        from langgraph.config import get_config  # noqa: PLC0415 - only graph runs have one
    except ImportError:
        return None
    try:
        configurable: dict[str, Any] = get_config().get("configurable") or {}
        return configurable
    except RuntimeError:
        return None


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
    if meta.get("startedBy") == "workflow":
        # A levy case (c-057): the parent case lists each child's outcome, read from its own meta.
        listed: list[dict[str, Any]] = list(cast(dict[str, Any], parent.get("meta") or {}).get("children") or [])
        entry = {
            "threadId": child["id"],
            "customerId": meta.get("customerId"),
            "subject": meta.get("subject"),
            "status": "finished",
            "outcome": values.get("status"),
            "hold": values.get("hold"),
            "note": values.get("note"),
        }
        others = [c for c in listed if c.get("threadId") != child["id"]]
        await graph_store(rt).merge_meta(parent["id"], {"children": [*others, entry]}, lock=True)
        await write_children_back(rt, parent["id"], child["id"])
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


async def write_children_back(rt: Runtime, parent_id: str, child_id: str) -> None:
    """Puts the children's current outcomes into the parent's checkpoint (`values.children`), under the parent's
    lease so the write carries a generation the fence accepts, as the node the parent finished at so no step is
    scheduled. A parent mid-run keeps its lease: the meta then holds the outcome and the state route reads it over
    the values, so nothing is lost; the next write-back carries it."""
    leases = rt.leases
    if leases is None:
        return
    from .hitl_facade import children_view  # noqa: PLC0415 - hitl_facade imports this module's neighbours

    run_id = f"run_child_{child_id[-12:]}"
    try:
        generation = await leases.acquire(parent_id, run_id)
    except LeaseHeldError:
        return
    try:
        row, graph = await resolve(rt, parent_id)
        snap = await graph.aget_state(config(parent_id))
        values: dict[str, Any] = snap.values or {}
        visited: list[str] = list(values.get("visited") or [])
        if not visited or snap.next:
            return  # not finished: its own run writes the state
        merged = children_view(values, row["meta"] or {})
        with as_thread_team(row):
            await graph.aupdate_state(
                config(parent_id, generation), {"children": merged}, as_node=visited[-1].split("@")[0]
            )
    finally:
        await leases.release(parent_id, run_id)


async def refusal(rt: Runtime, workflow: str) -> ApiError | None:
    """Why `workflow` cannot start now, as the registry says it (paused, deleted, never published, not a registry
    workflow); None when it can. A v2 workflow (workflow runner) can start while a version of it is live."""
    if await engine_workflow(rt, workflow) is not None:
        return None
    try:
        version = await thread_pin(rt, workflow)
    except ApiError as e:
        return e
    if version is None:
        return ValidationFailed(f"Workflow {workflow} is not published, so it cannot start.", code="not_published")
    return None


async def published_workflows(rt: Runtime) -> list[dict[str, Any]]:
    """The registry workflows a new thread can start on (live, published, not paused or deleted), with the name and
    description they are found by."""
    rows = await registry(rt).rows()
    return [r for r in rows if r["status"] not in ("paused", "deleted") and r["published_version"] is not None]


# How long a turn waits for a v2 workflow it started to end or pause; past it the turn gets the run's handle.
ENGINE_WAIT_SECONDS = 90.0
ENGINE_POLL_SECONDS = 0.25


async def engine_workflows(rt: Runtime) -> list[dict[str, Any]]:
    """The v2 workflows (workflow runner) the selected team can start, those with a live version, each described by its
    latest version; none on a database without the runner's tables."""
    try:
        found = await DefinitionStore(EngineTransactions(rt.db)).summaries(team=current_team())
        return [d for d in found if d["current_stage"] == "live"]
    except (DatabaseError, NoTenantError):
        # v2 workflows are tenant rows; a caller with no tenant (a v1 path outside a request) offers v1 ones alone.
        return []


async def engine_workflow(rt: Runtime, workflow: str) -> dict[str, Any] | None:
    try:
        return await DefinitionStore(EngineTransactions(rt.db)).live(workflow, team=current_team())
    except (DatabaseError, NoTenantError):
        return None


def engine_input_schema(definition: dict[str, Any]) -> dict[str, Any]:
    """The trigger node's declared input schema, else any object."""
    for n in cast(list[dict[str, Any]], definition.get("nodes") or []):
        if str(n.get("type", "")).startswith("ops.trigger."):
            schema = cast(dict[str, Any], n.get("parameters") or {}).get("inputSchema")
            if isinstance(schema, dict):
                return cast(dict[str, Any], schema)
    return {"type": "object"}


def engine_tool_description(row: dict[str, Any]) -> str:
    about = str(cast(dict[str, Any], row.get("definition") or {}).get("description") or "").strip()
    name = str(row.get("name") or row["workflow_id"])
    return f"{name}: {about} Starts the workflow and returns its outcome.".replace(":  ", ": ")


def workflow_tool_description(row: dict[str, Any]) -> str:
    """What an agent reads to choose the workflow: its registry name and description, and what the call does."""
    about = str(row.get("description") or "").strip()
    return f"{row['name']}: {about} Starts the workflow on an email and returns its outcome.".replace(":  ", ": ")


def _started_by(parent_meta: dict[str, Any]) -> str:
    agent = f"agent:{parent_meta.get('agentId') or parent_meta.get('agentName') or 'agent'}"
    person = TURN_PERSON.get()
    return f"{person.email} via {agent}" if person is not None else agent


async def run_child(rt: Runtime, thread_id: str, graph_input: dict[str, Any], *, run_id: str) -> None:
    """Runs a child thread (a workflow or a specialist's turn) to its end or its first pause, inside the parent's tool
    call. A retried parent turn meets the child's existing run and reads its outcome instead of starting it again."""
    store = graph_store(rt)
    require_graphs(rt)
    assert rt.leases is not None
    try:
        generation = await rt.leases.acquire(thread_id, run_id)
    except LeaseHeldError as e:
        raise Conflict("That child run is already running.", code="run_active") from e
    if not await store.start_run(run_id, thread_id, "input", now_iso(), {"input": graph_input}, generation=generation):
        await rt.leases.release(thread_id, run_id)
        return
    await store.set_thread_status(thread_id, "busy", now_iso(), generation=generation)
    row, graph = await resolve(rt, thread_id)
    async for _ in execute(rt, row, graph, graph_input=graph_input, run_id=run_id, kind="input"):
        pass


class ChildRuns:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def _refused_for_person(
        self, workflow: str, team: str | None, parent_thread_id: str | None
    ) -> ApiError | None:
        """Why the turn's person may not start `workflow` (owned by `team`), or None when they may, or when the run has
        no person and is not a chat (an unattended agent run, which acts as the agent)."""
        person = TURN_PERSON.get()
        if person is None:
            parent = await graph_store(self.rt).thread(parent_thread_id) if parent_thread_id else None
            if parent is not None and cast(dict[str, Any], parent["meta"] or {}).get("chat"):
                return Forbidden(
                    "This conversation's person is not known to this turn, so it starts no workflow; ask again.",
                    code="person_required",
                )
            return None
        try:
            can(caller_of(person), "workflows", "run", team=team, what=f"workflow {workflow}")
        except Forbidden as e:
            return e
        return None

    async def refused_for_person(self, workflow: str, team: str | None) -> ApiError | None:
        """Why the turn's person may not start `workflow`, or None when they may: the Ops tools' check (c-469)."""
        return await self._refused_for_person(workflow, team, None)

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
        rows = {r["id"]: r for r in await published_workflows(self.rt)}
        v2 = {r["workflow_id"]: r for r in await engine_workflows(self.rt)}
        parent_thread_id = str((_parent_meta_from_config() or {}).get("thread_id") or "") or None
        for name in granted:
            workflow = name.removeprefix("workflow:")
            row = rows.get(workflow)
            owner = (row or v2.get(workflow) or {}).get("team_id")
            if await self._refused_for_person(workflow, owner, parent_thread_id) is not None:
                continue  # the person may not start it, so the agent is not offered it on their behalf
            if row is None and workflow in v2:
                out.append(
                    ToolGrant(
                        name=f"{WORKFLOW_TOOL_PREFIX}{workflow}",
                        server="workflows",
                        description=engine_tool_description(v2[workflow]),
                        access="workflow",
                        input_schema=engine_input_schema(cast(dict[str, Any], v2[workflow]["definition"] or {})),
                    )
                )
                continue
            if row is None or await self._published(workflow) is None:
                continue  # unpublished, paused or unknown: the agent is not offered it
            out.append(
                ToolGrant(
                    name=f"{WORKFLOW_TOOL_PREFIX}{workflow}",
                    server="workflows",
                    description=workflow_tool_description(row),
                    access="workflow",
                    input_schema=EMAIL_SCHEMA,
                )
            )
        return out

    async def run(
        self,
        *,
        workflow: str,
        arguments: dict[str, Any],
        key: str,
        parent_thread_id: str,
        parent_run_id: str | None,
        graph_input: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ToolOutcome:
        store = graph_store(self.rt)
        pin = await self._published(workflow)
        stored = await engine_workflow(self.rt, workflow) if pin is None else None
        registry_row = (
            None
            if stored is not None
            else next((r for r in await published_workflows(self.rt) if r["id"] == workflow), None)
        )
        owner = (stored or registry_row or {}).get("team_id")
        # Checked again at the start, not only when offered: a model may name a tool it was never given.
        if (why := await self._refused_for_person(workflow, owner, parent_thread_id)) is not None:
            return ToolOutcome(ok=False, output={"error": why.message, "code": why.code})
        if stored is not None:
            return await self._run_engine(stored, arguments, key=key, parent_thread_id=parent_thread_id)
        if pin is None:
            why = await refusal(self.rt, workflow)
            message = why.message if why else f"Workflow {workflow} is not published, so it cannot start."
            return ToolOutcome(ok=False, output={"error": message, "code": why.code if why else "not_published"})
        parent = await store.thread(parent_thread_id)
        assert parent is not None, "a tool runs inside its parent's run"
        meta = {
            "startedBy": "agent",
            # The person a chat turn ran it for, beside the agent that started it (c-149).
            **({"startedFor": person.email} if (person := TURN_PERSON.get()) is not None else {}),
            "agentName": cast(dict[str, Any], parent["meta"] or {}).get("agentName") or "an agent",
            **(meta or {}),
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
                thread_id,
                graph_input or {"email": arguments},
                run_id="run_" + hashlib.sha256(key.encode()).hexdigest()[:16],
            )
        return await self._outcome(workflow, thread_id)

    async def _run_engine(
        self, stored: dict[str, Any], arguments: dict[str, Any], *, key: str, parent_thread_id: str
    ) -> ToolOutcome:
        """Starts a v2 workflow through the runner's queue, keyed by the tool call so a retried turn meets the same
        run, and waits for a worker to end or pause it. The output carries the run id, so the chat links the run."""
        parent = await graph_store(self.rt).thread(parent_thread_id)
        meta = cast(dict[str, Any], (parent or {}).get("meta") or {})
        runs = RunStore(EngineTransactions(self.rt.db))
        try:
            run, _ = await start_run(
                runs,
                stored,
                team_id=(parent or {}).get("team_id") or "local",
                mode="live",
                input=arguments,
                run_key=f"tool:{key}",
                # A chat turn starts it as its person, through the agent; an unattended run as the agent alone.
                created_by=_started_by(meta),
            )
        except (Conflict, NotFound) as e:
            return ToolOutcome(ok=False, output={"error": e.message, "code": "not_published"})
        except Forbidden as e:
            return ToolOutcome(ok=False, output={"error": e.message, "code": e.code})
        waited = 0.0
        while run["status"] not in (*TERMINAL, "waiting") and waited < ENGINE_WAIT_SECONDS:
            await asyncio.sleep(ENGINE_POLL_SECONDS)
            waited += ENGINE_POLL_SECONDS
            run = await runs.get(run["id"]) or run
        status = {"succeeded": "finished", "waiting": "waiting_review"}.get(str(run["status"]), str(run["status"]))
        out: dict[str, Any] = {"runId": run["id"], "workflow": stored["workflow_id"], "status": status}
        if run["status"] == "succeeded":
            out["outcome"] = run["output"]
        if run["status"] == "failed":
            out["error"] = run["error"]
        if run["status"] not in (*TERMINAL, "waiting"):
            # Not done within the wait: the run goes on (Cases and the run page show it), but the call did not finish,
            # so the model must not read it as a success.
            out["error"] = f"the workflow did not finish within {ENGINE_WAIT_SECONDS:.0f} seconds; it is still {status}"
        return ToolOutcome(ok=run["status"] in ("succeeded", "waiting"), output=out)

    async def _run(self, thread_id: str, graph_input: dict[str, Any], *, run_id: str) -> None:
        await run_child(self.rt, thread_id, graph_input, run_id=run_id)

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
