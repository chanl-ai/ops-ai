"""The four calls every graph runs through, mirroring LangGraph Server: create a thread, stream a run (with an input
or a resume), read the thread's state, list threads. Chat agents and workflows are both graphs here; the only
difference is which graph a thread was created for.

Each streamed event has one shape: `{event, runId, seq, node?, data?}` with `event` one of run_start, node_start,
node_end, text, tool_start, tool_end, interrupt, end, error.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from langgraph.types import Command
from pydantic import Field
from sse_starlette import EventSourceResponse

from ops_agents.graphs.definition import InvalidDefinitionError, WorkflowDefinition, validate
from ops_agents.graphs.metering import budget_from
from ops_contracts.chat import WireModel
from ops_service_kit.errors import (
    Conflict,
    NotFound,
    TooManyRequests,
    Unprocessable,
    ValidationFailed,
)
from ops_service_kit.ids import new_id, now_iso

from ...store.leases import LeaseHeldError
from ..agent_registry import refuse_new_turns
from ..auth import Principal, principal, require_step_up
from ..deps import Runtime, runtime
from ..envelope import ok
from ..event_log import REVIEW_KINDS
from ..runs import config, definition, execute, graph_store, pending, resolve
from ..schemas import (
    SSE_RESPONSE,
    Envelope,
    GraphPublished,
    GraphVersion,
    Migrated,
    RunJournalEntry,
    ThreadCreated,
    ThreadState,
    ThreadView,
)
from ..timers import sla_view
from ..usage import budget_view, totals_view
from ..workflow_registry import move_pointer, thread_pin

router = APIRouter(prefix="/v1/threads", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

# Fan-out across attachments runs at most this many tasks at once (LangGraph's own concurrency limit).
MAX_CONCURRENCY = 4
RECURSION_LIMIT = 60


class BudgetInput(WireModel):
    """Caps for one thread (E12); an unset cap does not limit. Cost is in the price table's currency."""

    max_calls: int | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, ge=0)
    max_cost: Decimal | None = Field(default=None, ge=0)


class ThreadInput(WireModel):
    graph: str
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])
    # For a definition-built workflow: the version to pin; the latest when left out.
    version: int | None = None
    # Channels: the key of what started the case. A thread with this key is returned instead of a new one (E6).
    external_key: str | None = None
    deployment_id: str | None = None
    parent_thread_id: str | None = None
    # Pauses the thread for a person when spent (E12); a deployment's default applies when left out.
    budget: BudgetInput | None = None


class MigrateInput(WireModel):
    to_version: int


class PublishInput(WireModel):
    definition: dict[str, Any]


class Decision(WireModel):
    decision: Literal["approved", "rejected"]
    reason: str | None = None
    step_up_token: str | None = None
    # From POST /v1/threads/{id}/approvals. It stays in the journaled resume input on purpose: a sweeper replaying a
    # crashed resume needs it, and it only authorises the one call it is bound to, until it expires.
    approval_token: str | None = None
    # Answering a budget_exhausted pause: approved with new caps continues, rejected stops the case (E12).
    budget: BudgetInput | None = None


class RunInput(WireModel):
    run_id: str | None = None
    input: dict[str, Any] | None = None
    resume: Decision | None = None


_store = graph_store
_config = config
_pending = pending
_definition = definition
_thread = resolve


def _thread_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "threadId": row["id"],
        "graph": row["graph"],
        "version": row["version"],
        "metadata": row["meta"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@router.post(
    "",
    response_model=Envelope[ThreadCreated],
    status_code=201,
    responses={200: {"model": Envelope[ThreadCreated], "description": "An existing thread with that external key"}},
)
async def create_thread(rt: Rt, me: Me, body: ThreadInput) -> JSONResponse:
    store = _store(rt)
    # The per-key ledger belongs to the models service; until then the port admits every key (E12).
    refusal = await rt.keys.admit(f"user:{me.email}")
    if refusal is not None:
        raise TooManyRequests(refusal.reason, code="key_budget_exhausted")
    thread_id = new_id("gth")
    version: int | None = None
    digest: str | None = None
    if body.graph.startswith("agent:") and rt.catalog.agent(body.graph.removeprefix("agent:")) is None:
        # Its graph stays compiled while turns under way drain; no new thread starts on it.
        await refuse_new_turns(rt, body.graph.removeprefix("agent:"))
        raise ValidationFailed(f"Unknown graph {body.graph}: that agent is not live.")
    if body.graph not in rt.graphs:
        # A registry workflow starts on its pointer and refuses while paused or unpublished; other definitions start
        # on their latest version.
        pinned = await thread_pin(rt, body.graph)
        versions = await store.versions(body.graph)
        if not versions:
            names = sorted({*rt.graphs, "dispute_email"})
            raise ValidationFailed(f"Unknown graph {body.graph}. Graphs: {', '.join(names)}.")
        wanted = body.version or pinned
        chosen = next((v for v in versions if v["version"] == wanted), None) if wanted else versions[-1]
        if chosen is None:
            raise NotFound(f"{body.graph} version {body.version}")
        version, digest = chosen["version"], chosen["digest"]
    if body.external_key is None:
        await store.create_thread(
            thread_id, body.graph, body.metadata, me.team_id, now_iso(), version=version, digest=digest
        )
        await _set_budget(rt, thread_id, body.budget, None)
        return ok(
            {"threadId": thread_id, "graph": body.graph, "version": version, "digest": digest, "created": True},
            status=201,
        )

    # Find-or-create by external key, one transaction. A paused deployment returns an existing case but opens none.
    default_budget: dict[str, Any] | None = None
    if body.deployment_id is not None:
        assert rt.channels is not None
        deployment = await rt.channels.deployment(body.deployment_id)
        if deployment is None:
            raise NotFound(f"Deployment {body.deployment_id}")
        default_budget = deployment.budget
        if deployment.paused:
            existing = await store.thread_by_key(body.external_key)
            if existing is None:
                raise Conflict(
                    f"Deployment {body.deployment_id} is paused; it opens no new cases.", code="deployment_paused"
                )
            return ok({"threadId": existing["id"], "graph": existing["graph"], "created": False})
    row, created = await store.find_or_create_thread(
        thread_id,
        body.graph,
        body.metadata,
        me.team_id,
        now_iso(),
        external_key=body.external_key,
        deployment_id=body.deployment_id,
        parent_thread_id=body.parent_thread_id,
        version=version,
        digest=digest,
    )
    if created:
        await _set_budget(rt, row["id"], body.budget, default_budget)
    data = {"threadId": row["id"], "graph": row["graph"], "version": row["version"], "created": created}
    return ok(data, status=201 if created else 200)


@router.get("", response_model=Envelope[list[ThreadView]])
async def list_threads(rt: Rt, graph: str | None = None) -> JSONResponse:
    return ok([_thread_view(r) for r in await _store(rt).threads(graph)])


@router.get("/{thread_id}/state", response_model=Envelope[ThreadState])
async def thread_state(rt: Rt, thread_id: str) -> JSONResponse:
    row, graph = await _thread(rt, thread_id)
    snap = await graph.aget_state(_config(thread_id))
    pending = _pending(snap)
    return ok(
        {
            "threadId": thread_id,
            "graph": row["graph"],
            "version": row["version"],
            "digest": row["digest"],
            "status": row["status"],
            "values": jsonable_encoder(snap.values),
            "next": list(snap.next),
            "interrupt": pending[0] if pending else None,
            "sla": await sla_view(rt, thread_id),
            "cost": totals_view(await rt.usage.totals(thread_id)) if rt.usage else None,
            "budget": budget_view(await rt.usage.budget(thread_id)) if rt.usage else None,
        }
    )


def _frame(event: dict[str, Any]) -> dict[str, str]:
    return {"data": json.dumps(jsonable_encoder(event), ensure_ascii=False)}


@router.post("/{thread_id}/runs/stream", response_model=None, responses=SSE_RESPONSE)
async def stream_run(rt: Rt, me: Me, thread_id: str, body: RunInput) -> EventSourceResponse:
    store = _store(rt)
    row, graph = await _thread(rt, thread_id)
    if (body.input is None) == (body.resume is None):
        raise ValidationFailed("Send exactly one of input or resume.")
    run_id = body.run_id or new_id("run")

    existing = await store.run(run_id)
    if existing is not None:
        if existing["thread_id"] != thread_id or existing["status"] == "running":
            raise Conflict("That run id is already in use.", code="run_active")
        replay: list[dict[str, Any]] = existing["events"]

        async def replayed() -> AsyncIterator[dict[str, str]]:
            for e in replay:
                yield _frame(e)

        return EventSourceResponse(replayed(), sep="\n", ping=15)

    snap = await graph.aget_state(_config(thread_id))
    waiting = _pending(snap)
    if body.resume is not None:
        if not waiting:
            raise Conflict("This thread is not waiting for a decision.", code="run_not_waiting")
        payload = waiting[0]["payload"]
        if isinstance(payload, dict) and payload.get("kind") in REVIEW_KINDS:  # pyright: ignore[reportUnknownMemberType]
            # A review policy owns this step: the decision is recorded, checked (requester, step-up, approvers) and
            # resumed by POST /reviews/{id}/decision, so a resume here would skip all three.
            raise Conflict(
                "This step is decided in Reviews: POST /reviews/{threadId}/decision.", code="resume_via_review"
            )
        if (
            body.resume.decision == "approved" and isinstance(payload, dict) and payload.get("step_up")  # pyright: ignore[reportUnknownMemberType]
        ):
            require_step_up(rt, me.email, body.resume.step_up_token)
        if (
            rt.gateway
            and body.resume.decision == "approved"
            and isinstance(payload, dict)
            and payload.get("call")  # pyright: ignore[reportUnknownMemberType]
            and not body.resume.approval_token
        ):
            # Checked here, before the graph runs: an approved decision without its token would let the review node
            # finish and leave the thread retrying a call the gateway will always refuse.
            raise Unprocessable(
                "This approval needs its token: POST /v1/threads/{id}/approvals first, then resume with approvalToken.",
                code="approval_token_required",
            )
        # JSON mode: a budget's Decimal cap travels as a string through the checkpointed resume value.
        resume = body.resume.model_dump(mode="json", exclude_none=True)
        graph_input: Any = Command(resume=resume)
        journal_input: dict[str, Any] = {"resume": resume}
    else:
        if waiting:
            raise Conflict("This thread is waiting for a decision; resume it instead.", code="run_waiting")
        # A paused agent takes no new turn on its own graph or the shared wrapper; a turn already under way finishes.
        if row["graph"].startswith("agent:"):
            await refuse_new_turns(rt, row["graph"].removeprefix("agent:"))
        elif row["graph"] == "agent_wrapper" and isinstance(body.input, dict) and body.input.get("agent_id"):
            await refuse_new_turns(rt, str(body.input["agent_id"]))
        graph_input = body.input
        journal_input = {"input": body.input}
    assert rt.leases is not None
    try:
        generation = await rt.leases.acquire(thread_id, run_id)
    except LeaseHeldError as e:
        age = e.held.age
        raise Conflict(
            f"A run is already active on this thread (held by {e.held.owner} for {age:.1f}s).",
            code="run_active",
            details={"owner": e.held.owner, "runId": e.held.run_id, "ageSeconds": round(age, 1)},
        ) from e
    kind = "resume" if body.resume else "input"
    if not await store.start_run(run_id, thread_id, kind, now_iso(), journal_input, generation=generation):
        await rt.leases.release(thread_id, run_id)
        raise Conflict("That run id is already in use.", code="run_active")
    await store.set_thread_status(thread_id, "busy", now_iso(), generation=generation)

    async def stream() -> AsyncIterator[dict[str, str]]:
        async for e in execute(rt, row, graph, graph_input=graph_input, run_id=run_id, kind=kind):
            yield _frame(e)

    return EventSourceResponse(stream(), sep="\n", ping=15)


@router.get("/{thread_id}/runs", response_model=Envelope[list[RunJournalEntry]])
async def thread_runs(rt: Rt, thread_id: str) -> JSONResponse:
    """The thread's run journal: each run's kind (input, resume, recovery), status and node sequence."""
    await _thread(rt, thread_id)
    rows = await _store(rt).runs(thread_id)
    by_run = await rt.usage.totals_by_run(thread_id) if rt.usage else {}
    return ok(
        [
            {
                "runId": r["id"],
                "kind": r["kind"],
                "status": r["status"],
                "createdAt": r["created_at"],
                "finishedAt": r["finished_at"],
                "nodes": [e["node"] for e in r["events"] if e.get("event") == "node_start"],
                "owner": next((e["data"].get("owner") for e in r["events"] if e.get("event") == "run_start"), None),
                "generation": next(
                    (e["data"].get("generation") for e in r["events"] if e.get("event") == "run_start"), None
                ),
                # Set by the sweeper for a run whose process died: owner, nodes it was running, generation.
                "crashed": next((e["data"] for e in r["events"] if e.get("event") == "crashed"), None),
                "cost": totals_view(by_run[r["id"]]) if r["id"] in by_run else None,
            }
            for r in rows
        ]
    )


@router.post("/{thread_id}/migrate", response_model=Envelope[Migrated])
async def migrate(rt: Rt, thread_id: str, body: MigrateInput) -> JSONResponse:
    """Moves a paused thread to another version of its workflow. Allowed only while it waits on an interrupt, and only
    when every node it is waiting in exists under the same name in the target, so the resume lands on a real node."""
    row, graph = await _thread(rt, thread_id)
    if row["graph"] in rt.graphs:
        raise ValidationFailed(f"{row['graph']} is a code graph with no versions to migrate between.")
    snap = await graph.aget_state(_config(thread_id))
    if not _pending(snap):
        raise Conflict("Only a thread waiting on a decision can be migrated.", code="not_waiting")
    target = await _definition(rt, row["graph"], body.to_version)
    missing = [n for n in snap.next if target.node(n) is None]
    if missing:
        raise Conflict(
            f"Version {body.to_version} has no node named {', '.join(missing)}, where this thread is waiting.",
            code="node_missing",
        )
    await _store(rt).pin(thread_id, target.version, target.digest(), now_iso())
    return ok(
        {
            "threadId": thread_id,
            "fromVersion": row["version"],
            "toVersion": target.version,
            "waitingAt": list(snap.next),
        }
    )


versions_router = APIRouter(prefix="/v1/graphs", dependencies=[Depends(principal)])


@versions_router.get("/{name}/versions", response_model=Envelope[list[GraphVersion]])
async def list_versions(rt: Rt, name: str) -> JSONResponse:
    return ok(
        [
            {"name": v["name"], "version": v["version"], "digest": v["digest"], "createdAt": v["created_at"]}
            for v in await _store(rt).versions(name)
        ]
    )


@versions_router.post("/{name}/versions", response_model=Envelope[GraphPublished], status_code=201)
async def publish_version(rt: Rt, name: str, body: PublishInput) -> JSONResponse:
    try:
        d = WorkflowDefinition.model_validate({**body.definition, "name": name, "version": 0})
        validate(d)
    except (ValueError, InvalidDefinitionError) as e:
        raise ValidationFailed(f"Invalid workflow definition: {e}") from e
    version = await _store(rt).publish(name, d.model_dump(mode="json"), d.digest(), now_iso())
    # This route publishes without a review, and its callers expect the next thread to start on what it published.
    await move_pointer(rt, name, version)
    return ok({"name": name, "version": version, "digest": d.digest()}, status=201)


async def _set_budget(rt: Runtime, thread_id: str, given: BudgetInput | None, default: dict[str, Any] | None) -> None:
    if rt.usage is None:
        return
    raw = given.model_dump(exclude_none=True) if given is not None else default
    if raw:
        await rt.usage.set_budget(thread_id, budget_from(raw))
