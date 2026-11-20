"""Workflows as agent tools, API side (docs/architecture/workflows-as-tools.md): the `WorkflowRunner` port an agent
turn reaches through `GraphDeps.workflows`.

A call finds or creates the child thread keyed by the tool call's idempotency key (`external_key`), so a turn
retried after a crash meets the same child; runs it under the child's own lease, exactly as a route would; and
returns its result, or a handle when it stopped at a review, which Cases and Reviews then show like any workflow.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, cast

from ops_access import can
from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import ToolGrant
from ops_agents.graphs.common import WORKFLOW_TOOL_PREFIX
from ops_engine.store import TERMINAL, DefinitionRow, DefinitionStore, RunStore
from ops_service_kit import narrow
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound, Unprocessable, ValidationFailed
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import get_logger

from ..store.engine import DatabaseError, EngineTransactions
from ..store.events import EventLog
from ..store.graphs import StoredThread
from ..store.leases import LeaseHeldError
from ..store.tenancy import NoTenantError, current_team
from .auth import Principal, caller_of
from .deps import Runtime
from .engine_runs import start_run
from .runs import as_thread_team, config, execute, graph_store, pending, require_graphs, resolve
from .workflow_registry import registry, thread_pin

log = get_logger("ops_agents.api.child_runs")

# The person a chat turn runs for. A workflow or an agent that an agent holds as a tool is offered and started only
# when that person may reach it: the turn's authority is the person's rights and the agent's grants together. A turn
# with no person follows `refused_with_no_person`.
TURN_PERSON: ContextVar[Principal | None] = ContextVar("ops_turn_person", default=None)


def refused_with_no_person(parent: StoredThread | None, team: str | None, what: str) -> ApiError | None:
    """Why a turn with no person, on thread `parent`, may not reach `what` (a workflow or an agent owned by `team`);
    None when it may. The one rule for such a turn, whatever it reaches: a chat turn whose person is not known (one
    resumed after a decision) reaches nothing; any other run (a scheduled or otherwise unattended agent run) acts as
    its agent, which reaches what its own team owns and what no team owns. Both teams are the server's: the thread's
    was set from its starter's token, the target's by its registry."""
    if parent is None:
        return None
    if parent.meta_object().get("chat"):
        return Forbidden(
            f"This conversation's person is not known to this turn, so it does not reach {what}; ask again.",
            code="person_required",
        )
    if team and team != parent.team_id:
        return Forbidden(
            f"A run with no person acts as its agent, in its own team, so it does not reach {what} of another team.",
            code="other_team",
        )
    return None


@contextmanager
def acting_for(person: Principal) -> Generator[None]:
    token = TURN_PERSON.set(person)
    try:
        yield
    finally:
        TURN_PERSON.reset(token)


def _parent_thread_id() -> str | None:
    """The thread of the graph run this call is inside, from its config; None outside a graph run."""
    try:
        from langgraph.config import get_config  # noqa: PLC0415 - only graph runs have one
    except ImportError:
        return None
    try:
        configurable: Mapping[str, object] = get_config().get("configurable") or {}
    except RuntimeError:
        return None
    return str(configurable.get("thread_id") or "") or None


# A definition's input is the email its nodes read (WorkflowState.email).
EMAIL_SCHEMA: Json = {
    "type": "object",
    "properties": {
        "sender": {"type": "string", "description": "Who the email is from"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["sender", "subject", "body"],
}


async def tell_parent(rt: Runtime, child: Mapping[str, JsonValue]) -> None:
    """A child an agent started has finished: its outcome goes on the parent thread as a `child_finished` event, which
    the conversation shows after the turn that started it. No model call; the person reads the outcome."""
    meta = narrow.an_object(child.get("meta") or {}, "thread meta")
    parent_id = meta.get("parentThreadId")
    parent = await graph_store(rt).thread_row(str(parent_id)) if parent_id else None
    if parent is None:
        return
    child_id = str(child["id"])
    _, graph = await resolve(rt, child_id)
    # Workflow state: the JSON a workflow's nodes write.
    values: Json = (await graph.aget_state(config(child_id))).values or {}
    if meta.get("startedBy") == "workflow":
        # A levy case: the parent case lists each child's outcome, read from its own meta.
        listed = narrow.entries(parent.meta_object().get("children"))
        entry: Json = {
            "threadId": child_id,
            "customerId": meta.get("customerId"),
            "subject": meta.get("subject"),
            "status": "finished",
            "outcome": values.get("status"),
            "hold": values.get("hold"),
            "note": values.get("note"),
        }
        others = [c for c in listed if narrow.an_object(c, "a listed child").get("threadId") != child_id]
        await graph_store(rt).merge_meta(parent.id, {"children": [*others, entry]}, lock=True)
        await write_children_back(rt, parent.id, child_id)
    await EventLog(graph_store(rt).engine).append(
        thread_id=parent.id,
        team_id=parent.team_id,
        run_id=None,
        type_="child_finished",
        data={
            "childThreadId": child_id,
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
        values: Json = snap.values or {}
        visited = list(cast(list[str], values.get("visited") or []))
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
    # As dicts with the columns' names: the tool catalogue's and the skills' readers, and their test stand-ins.
    return [r.model_dump() for r in rows if r.status not in ("paused", "deleted") and r.published_version is not None]


# How long a turn waits for a v2 workflow it started to end or pause; past it the turn gets the run's handle.
ENGINE_WAIT_SECONDS = 90.0
ENGINE_POLL_SECONDS = 0.25


async def engine_workflows(rt: Runtime) -> list[dict[str, Any]]:
    """The v2 workflows (workflow runner) the selected team can start, those with a live version, each described by its
    latest version; none on a database without the runner's tables."""
    try:
        found = await DefinitionStore(EngineTransactions(rt.db)).summaries(team=current_team())
        # The tool and catalog readers still read each summary as its stored mapping.
        return [d.model_dump() for d in found if d.current_stage == "live"]
    except (DatabaseError, NoTenantError):
        # v2 workflows are tenant rows; a caller with no tenant (a v1 path outside a request) offers v1 ones alone.
        return []


async def team_workflows(rt: Runtime) -> list[dict[str, Any]]:
    """Every v2 workflow the selected team holds, each described by its newest version, whatever its stage; none on a
    database without the runner's tables."""
    try:
        return [d.model_dump() for d in await DefinitionStore(EngineTransactions(rt.db)).summaries(team=current_team())]
    except (DatabaseError, NoTenantError):
        return []


async def engine_workflow(rt: Runtime, workflow: str) -> DefinitionRow | None:
    try:
        return await DefinitionStore(EngineTransactions(rt.db)).live(workflow, team=current_team())
    except (DatabaseError, NoTenantError):
        return None


def engine_input_schema(definition: Json) -> Json:
    """The trigger node's declared input schema, else any object."""
    for n in narrow.entries(definition.get("nodes")):
        node = narrow.an_object(n, "workflow node")
        if str(node.get("type", "")).startswith("ops.trigger."):
            schema = narrow.an_object(node.get("parameters") or {}, "node parameters").get("inputSchema")
            if isinstance(schema, dict):
                return schema
    return {"type": "object"}


def engine_tool_description(row: Mapping[str, JsonValue]) -> str:
    about = str(narrow.an_object(row.get("definition") or {}, "workflow definition").get("description") or "").strip()
    name = str(row.get("name") or row["workflow_id"])
    return f"{name}: {about} Starts the workflow and returns its outcome.".replace(":  ", ": ")


def workflow_tool_description(row: Mapping[str, JsonValue]) -> str:
    """What an agent reads to choose the workflow: its registry name and description, and what the call does."""
    about = str(row.get("description") or "").strip()
    return f"{row['name']}: {about} Starts the workflow on an email and returns its outcome.".replace(":  ", ": ")


def _started_by(parent_meta: Json) -> str:
    agent = f"agent:{parent_meta.get('agentId') or parent_meta.get('agentName') or 'agent'}"
    person = TURN_PERSON.get()
    return f"{person.email} via {agent}" if person is not None else agent


async def run_child(rt: Runtime, thread_id: str, graph_input: Json, *, run_id: str) -> None:
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
        """Why the turn's person may not start `workflow` (owned by `team`), or None when they may; for a turn with
        no person, `refused_with_no_person`."""
        person = TURN_PERSON.get()
        if person is None:
            parent = await graph_store(self.rt).thread_row(parent_thread_id) if parent_thread_id else None
            return refused_with_no_person(parent, team, f"workflow {workflow}")
        try:
            can(caller_of(person), "workflows", "run", team=team, what=f"workflow {workflow}")
        except Forbidden as e:
            return e
        return None

    async def refused_for_person(self, workflow: str, team: str | None) -> ApiError | None:
        """Why the turn's person may not start `workflow`, or None when they may: the Ops tools' check."""
        return await self._refused_for_person(workflow, team, None)

    async def _published(self, workflow: str) -> tuple[int, str] | None:
        """The registry's published version of `workflow` and its digest; None when it is not a registry workflow or is
        paused, deleted or never published."""
        try:
            version = await thread_pin(self.rt, workflow)
        except ApiError:
            return None
        stored = await graph_store(self.rt).version(workflow, version) if version is not None else None
        return (version, stored.digest) if version is not None and stored else None

    async def offers(self, granted: list[str]) -> list[ToolGrant]:
        out: list[ToolGrant] = []
        rows = {r["id"]: r for r in await published_workflows(self.rt)}
        v2 = {r["workflow_id"]: r for r in await engine_workflows(self.rt)}
        parent_thread_id = _parent_thread_id()
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
                        input_schema=engine_input_schema(
                            narrow.an_object(v2[workflow]["definition"] or {}, "workflow definition")
                        ),
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
        arguments: Json,
        key: str,
        parent_thread_id: str,
        parent_run_id: str | None,
        graph_input: Json | None = None,
        meta: Json | None = None,
    ) -> ToolOutcome:
        store = graph_store(self.rt)
        pin = await self._published(workflow)
        stored = await engine_workflow(self.rt, workflow) if pin is None else None
        registry_row = (
            None
            if stored is not None
            else next((r for r in await published_workflows(self.rt) if r["id"] == workflow), None)
        )
        owner = stored.team_id if stored is not None else (registry_row or {}).get("team_id")
        # Checked again at the start, not only when offered: a model may name a tool it was never given.
        if (why := await self._refused_for_person(workflow, owner, parent_thread_id)) is not None:
            return ToolOutcome(ok=False, output={"error": why.message, "code": why.code})
        if stored is not None:
            return await self._run_engine(stored, arguments, key=key, parent_thread_id=parent_thread_id)
        if pin is None:
            why = await refusal(self.rt, workflow)
            message = why.message if why else f"Workflow {workflow} is not published, so it cannot start."
            return ToolOutcome(ok=False, output={"error": message, "code": why.code if why else "not_published"})
        parent = await store.thread_row(parent_thread_id)
        assert parent is not None, "a tool runs inside its parent's run"
        thread_meta: Json = {
            "startedBy": "agent",
            # The person a chat turn ran it for, beside the agent that started it.
            **({"startedFor": person.email} if (person := TURN_PERSON.get()) is not None else {}),
            "agentName": parent.meta_object().get("agentName") or "an agent",
            **(meta or {}),
            "parentThreadId": parent_thread_id,
            "parentRunId": parent_run_id,
        }
        row, created = await store.open_thread(
            new_id("gth"),
            workflow,
            thread_meta,
            parent.team_id,
            now_iso(),
            external_key=f"tool:{key}",
            parent_thread_id=parent_thread_id,
            version=pin[0],
            digest=pin[1],
        )
        thread_id = row.id
        if created:
            await self._run(
                thread_id,
                graph_input or {"email": arguments},
                run_id="run_" + hashlib.sha256(key.encode()).hexdigest()[:16],
            )
        return await self._outcome(workflow, thread_id)

    async def _run_engine(
        self, stored: DefinitionRow, arguments: Json, *, key: str, parent_thread_id: str
    ) -> ToolOutcome:
        """Starts a v2 workflow through the runner's queue, keyed by the tool call so a retried turn meets the same
        run, and waits for a worker to end or pause it. The output carries the run id, so the chat links the run."""
        parent = await graph_store(self.rt).thread_row(parent_thread_id)
        meta = parent.meta_object() if parent is not None else {}
        runs = RunStore(EngineTransactions(self.rt.db))
        try:
            run, _ = await start_run(
                runs,
                stored,
                team_id=(parent.team_id if parent is not None else "") or "local",
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
        except Unprocessable as e:
            # The arguments do not match the workflow's input: the agent reads which field and why, and may call again.
            return ToolOutcome(ok=False, output={"error": e.message, "code": e.code, "details": e.details})
        waited = 0.0
        while run.status not in (*TERMINAL, "waiting") and waited < ENGINE_WAIT_SECONDS:
            await asyncio.sleep(ENGINE_POLL_SECONDS)
            waited += ENGINE_POLL_SECONDS
            run = await runs.row(run.id) or run
        status = {"succeeded": "finished", "waiting": "waiting_review"}.get(run.status, run.status)
        out: Json = {"runId": run.id, "workflow": stored.workflow_id, "status": status}
        if run.status == "succeeded":
            out["outcome"] = run.output
        if run.status == "failed":
            out["error"] = run.error
        if run.status not in (*TERMINAL, "waiting"):
            # Not done within the wait: the run goes on (Cases and the run page show it), but the call did not finish,
            # so the model must not read it as a success.
            out["error"] = f"the workflow did not finish within {ENGINE_WAIT_SECONDS:.0f} seconds; it is still {status}"
        return ToolOutcome(ok=run.status in ("succeeded", "waiting"), output=out)

    async def _run(self, thread_id: str, graph_input: Json, *, run_id: str) -> None:
        await run_child(self.rt, thread_id, graph_input, run_id=run_id)

    async def _outcome(self, workflow: str, thread_id: str) -> ToolOutcome:
        _, graph = await resolve(self.rt, thread_id)
        snap = await graph.aget_state(config(thread_id))
        values: Json = snap.values or {}
        base: Json = {"workflow": workflow, "threadId": thread_id}
        if pending(snap):
            # Decided in Cases and Reviews like any workflow review; the parent does not wait for it.
            return ToolOutcome(ok=True, output=base | {"status": "waiting_review", "reviewId": thread_id})
        runs = await graph_store(self.rt).runs(thread_id)
        if runs and runs[-1].status == "error":
            return ToolOutcome(ok=False, output=base | {"status": "failed"})
        return ToolOutcome(ok=True, output=base | {"status": "finished", "outcome": values.get("status")})
