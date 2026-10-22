"""The workflow runner's routes (docs/architecture/workflow-runner.md): the node type registry the editor, the validator
and the runner all read, and v2 definitions (YAML or JSON in, JSON stored). Mounted before `workflows.router`, whose
`/v1/workflows/{workflow_id}` would otherwise take `node-types` as an id. v1 definitions stay on /v1/graphs."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, model_validator
from sse_starlette import EventSourceResponse

from ops_agent_kernel.pii import masked
from ops_contracts.chat import WireModel
from ops_documents_client import DocumentNotFound, DocumentsClient
from ops_engine import default_registry
from ops_engine.compiler import redacted
from ops_engine.definition import InvalidDefinitionError, WorkflowDefinition, advise, parse, validate
from ops_engine.document_types import pinned, unpinned
from ops_engine.store import (
    TERMINAL,
    DefinitionStore,
    RunStore,
    WorkflowOwnedError,
)
from ops_engine.store.definitions import HUMAN_REVIEW
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound, Unprocessable
from ops_service_kit.http import Envelope, ListResult, paged
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger

from ...store.engine import DatabaseError, EngineTransactions
from ...store.events import EventLog
from ...store.mailboxes import MailboxStore
from ...store.tenancy import current_team, current_tenant
from .. import ai_steps_gate, engine_lifecycle, step_shapes, task_view
from ..actors import ActorView, actors, started_by_of
from ..agent_registry import registry as agent_registry
from ..auth import (
    Principal,
    key_scope,
    principal,
    require_builder,
    require_key_reaches,
    require_runs_cancel,
    require_runs_start,
    started_by,
)
from ..deps import Runtime, runtime
from ..email_trigger import binding_of
from ..engine_runs import live_version, start_run
from ..envelope import ok
from ..file_names import named
from ..schemas import SSE_RESPONSE, Out, PublishReview
from .tool_catalog import known_tools

router = APIRouter(prefix="/v1/workflows", dependencies=[Depends(principal)])

REGISTRY = default_registry()
log = get_logger("ops_agents.api.routers.engine")
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class PortView(Out):
    name: str
    connection: str
    label: str


class RetryView(Out):
    attempts: int
    backoff_seconds: list[float]


class OptionalPortView(Out):
    parameter: str
    # The parameter's value as the definition holds it (a string or a boolean); "*" matches any value set.
    value: Any
    port: str


class NodeTypeView(Out):
    id: str
    version: int
    group: str
    label: str
    description: str
    inputs: list[PortView]
    outputs: list[PortView]
    # The list parameter whose entries become the out ports (a review's options); the declared outputs are its default.
    outputs_from: str | None
    # Out ports every instance has besides those outputs_from lists, such as a Switch's otherwise (c-259).
    extra_outputs: list[str] = Field(default_factory=list[str])
    # An extra out port the instance has while `parameter` is `value` (a review's `timeout` when it expires).
    optional_outputs: list[OptionalPortView]
    # A declared out port the instance drops while `parameter` is `value` (Run workflow's `started` when it waits).
    outputs_unless: list[OptionalPortView] = Field(default_factory=list[OptionalPortView])
    parameters: dict[str, Any]
    effects: str
    retry: RetryView
    executor: str
    timeout_seconds: float
    # The generated form for `parameters`: field order, and per field its label, widget, help and option source.
    ui: dict[str, Any]
    # Why the acting team cannot add this step now (an AI step while its setting is off, c-298); None when it can.
    unavailable: str | None = None


@router.get("/node-types", response_model=Envelope[list[NodeTypeView]])
async def node_types(rt: Rt, me: Me) -> JSONResponse:
    """Every registered node type at every version: ports with their connection types, parameters as JSON Schema with
    the form generated from them, effects, retry and executor, and why the acting team cannot use one now."""
    ai_on = await ai_steps_gate.allowed(rt, current_team() or me.team_id or None)
    return ok(
        [
            {
                **t.view(),
                "unavailable": ai_steps_gate.OFF if t.executor == ai_steps_gate.EXECUTOR and not ai_on else None,
            }
            for t in REGISTRY.all()
        ]
    )


class DefinitionInput(WireModel):
    """Exactly one of `yaml` (YAML or JSON text) and `definition` (the parsed object)."""

    yaml: str | None = None
    definition: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one(self) -> DefinitionInput:
        if (self.yaml is None) == (self.definition is None):
            raise ValueError("send exactly one of yaml and definition")
        return self


class DefinitionCheck(Out):
    # None for a check about the whole definition (no trigger, a connection to a missing node).
    node: str | None
    level: str
    code: str
    message: str
    # The top-level parameter a schema error names, so the editor shows the message under that field; None otherwise.
    field: str | None = None


class DefinitionValidation(Out):
    ok: bool
    workflow_id: str | None
    digest: str | None
    checks: list[DefinitionCheck]


class DefinitionWarning(Out):
    node: str
    field: str
    message: str


class DefinitionPublished(Out):
    workflow_id: str
    version: int
    digest: str
    # False when this exact definition was stored before; its version is returned.
    created: bool
    # What the definition leaves out that does not stop it saving, such as a typed review step's missing param (c-288).
    warnings: list[DefinitionWarning] = Field(default_factory=list[DefinitionWarning])


Stage: TypeAlias = Literal["draft", "in_review", "live", "paused", "superseded"]  # noqa: UP040


class DefinitionVersion(Out):
    version: int
    digest: str
    created_at: str
    created_by: str
    stage: Stage


class OpenPublishRequest(Out):
    id: str
    version: int
    requested_by: str
    created_at: str


class DefinitionView(Out):
    workflow_id: str
    name: str
    version: int
    digest: str
    # The shown version's stage; in_review while a publish request for it is open.
    stage: Stage
    definition: dict[str, Any]
    versions: list[DefinitionVersion]
    # The version live runs start on (live or paused); None before the first approval.
    live_version: int | None
    paused: bool
    review: OpenPublishRequest | None
    # When the workflow was archived (c-274); None while it is not.
    archived_at: str | None = None


def definitions(rt: Runtime) -> DefinitionStore:
    return DefinitionStore(EngineTransactions(rt.db))


def _parsed(body: DefinitionInput) -> WorkflowDefinition:
    try:
        return parse(body.yaml if body.yaml is not None else body.definition or {})
    except InvalidDefinitionError as e:
        raise Unprocessable(f"Invalid workflow definition: {e}", code="invalid_definition") from e


@router.post("/definitions/validate", response_model=Envelope[DefinitionValidation])
async def validate_definition(rt: Rt, body: DefinitionInput) -> JSONResponse:
    """Per-node checks against the type registry: unknown type or version, unknown port, an out port that leads
    nowhere (End has none), an unreachable node, parameters that do not match the type's schema; and warnings that
    never refuse a save (level `warning`, e.g. a step two branches meet at without a Join). Saves nothing."""
    try:
        d = parse(body.yaml if body.yaml is not None else body.definition or {})
    except InvalidDefinitionError as e:
        check = {"node": None, "level": "error", "code": "invalid_definition", "message": str(e)}
        return ok({"ok": False, "workflowId": None, "digest": None, "checks": [check]})
    checks = validate(d, REGISTRY)
    warnings = advise(d, REGISTRY) + await step_shapes.field_warnings(rt, current_team() or "", d)
    return ok({"ok": not checks, "workflowId": d.id, "digest": d.digest(), "checks": checks + warnings})


@router.post(
    "/definitions",
    response_model=Envelope[DefinitionPublished],
    status_code=201,
    responses={200: {"model": Envelope[DefinitionPublished], "description": "This definition was stored before"}},
)
async def create_definition(rt: Rt, me: Me, body: DefinitionInput) -> JSONResponse:
    """Stores the definition as the workflow's next version, once it passes every check; the same definition again
    returns its version (200). A definition with failing checks is refused with them in `details.checks`. 403 unless
    the caller is a builder or admin of the team that owns the workflow (the acting team for a new one)."""
    d = _parsed(body)
    held = await definitions(rt).get(d.id, team=current_team())
    if held is not None:
        engine_lifecycle.require_rights(me, held, "save")
    else:
        require_builder(me, area="workflows", team_id=current_team(), action="save", what="a workflow")
    checks = validate(d, REGISTRY)
    if checks:
        raise Unprocessable(
            f"The definition has {len(checks)} failing checks.", code="definition_checks", details={"checks": checks}
        )
    owner = held["team_id"] if held is not None else current_team() or me.team_id or None
    if (uses := ai_steps_gate.ai_nodes(d, REGISTRY)) and not await ai_steps_gate.allowed(rt, owner):
        raise Unprocessable(
            f"{ai_steps_gate.OFF} Steps: {', '.join(uses)}.", code="ai_steps_off", details={"nodes": uses}
        )
    if wanted := unpinned(d.wire()):
        acting = current_team() or (held["team_id"] if held is not None else None) or me.team_id
        d = parse(pinned(d.wire(), await _newest_versions(rt, wanted, team=acting)))
    digest = d.digest()
    # An existing workflow keeps its owner, a shared one (no team) included, so a team's builder edits a shared
    # workflow through review instead of being told it is another team's.
    team = held["team_id"] if held is not None else current_team()
    if held is None and team is None and binding_of(d.wire()) is not None:
        # A dev session acts across teams and saves workflows no team owns, but a workflow that watches a mailbox
        # must belong to the mailbox's team (email_trigger.bindable): a new one is saved under the acting team, an
        # existing one keeps its owner.
        team = held["team_id"] if held is not None else (me.team_id or None)
    try:
        version, created = await definitions(rt).publish(
            d.id,
            name=d.name or d.id,
            definition=d.wire(),
            digest=digest,
            now=now_iso(),
            by=me.email,
            team=team,
        )
    except WorkflowOwnedError as e:
        raise Conflict(f"{d.id} is another team's workflow; choose another id.", code="workflow_owned") from e
    found = advise(d, REGISTRY) + await step_shapes.field_warnings(rt, team or current_team() or "", d)
    advice = [{"node": w["node"], "field": w["field"], "message": w["message"]} for w in found]
    warnings = await task_view.step_warnings(rt, d.wire()) + advice
    data = {"workflowId": d.id, "version": version, "digest": digest, "created": created, "warnings": warnings}
    return ok(data, status=201 if created else 200)


async def _newest_versions(rt: Runtime, type_ids: set[str], *, team: str | None) -> dict[str, int]:
    """Each document type's newest version in documents-service, read as the workflow's team (c-236, c-256), so the
    saved definition pins it. An unknown type, or one of another team, refuses the save."""
    if not rt.settings.documents_url or team is None:
        raise Unprocessable(
            "Document types are read from documents-service, which this service cannot reach.",
            code="document_type_unreachable",
        )
    documents = DocumentsClient.from_settings(rt.settings, service="agents", scopes=["documents:view"])
    try:
        out: dict[str, int] = {}
        for type_id in sorted(type_ids):
            try:
                found = await documents.document_type(current_tenant(), team, type_id)
            except DocumentNotFound as e:
                raise Unprocessable(f"No document type {type_id} in this team.", code="document_type_not_found") from e
            out[type_id] = int(found["latestVersion"])
        return out
    finally:
        await documents.aclose()


def page(rows: list[dict[str, Any]], page_no: int, size: int) -> dict[str, Any]:
    """The shared list envelope's data and pagination (as hitl_facade.page; imported from there it closes a cycle)."""
    total = len(rows)
    pages = max(1, -(-total // size))
    start = (page_no - 1) * size
    meta = {"page": page_no, "pageSize": size, "total": total, "totalPages": pages}
    meta |= {"hasNext": page_no < pages, "hasPrev": page_no > 1}
    return {"data": rows[start : start + size], "pagination": meta}


class DefinitionRow(Out):
    workflow_id: str
    name: str
    version: int
    digest: str
    # live or paused once a version is approved (the serving version's stage); before that the latest version's
    # stage, in_review while its publish request is open; archived once archived, whatever its stage (c-274).
    status: Literal["draft", "in_review", "live", "paused", "archived"]
    live_version: int | None
    runs: int
    updated_at: str
    updated_by: str


@router.get("/definitions", response_model=Envelope[ListResult[DefinitionRow]])
async def list_definitions(
    *,
    request: Request,
    rt: Rt,
    page_no: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: str | None = None,
    sort_by: Annotated[str | None, Query(alias="sortBy")] = None,
    sort_order: Annotated[Literal["asc", "desc"], Query(alias="sortOrder")] = "desc",
) -> JSONResponse:
    """The team's v2 workflows, each at its latest version, with the shared list pattern: search over name and id,
    status facets (draft, in review, live, paused) before the status filter, sort and pages. v1 workflows stay on
    /v1/workflows."""
    open_requests = await pending_requests(rt)
    rows: list[dict[str, Any]] = [
        {
            "workflowId": d["workflow_id"],
            "name": d["name"],
            "version": d["version"],
            "digest": d["digest"],
            "status": workflow_status(d, open_requests.get(d["workflow_id"])),
            "liveVersion": d["current_version"],
            "runs": d["runs"],
            "updatedAt": d["created_at"],
            "updatedBy": d["created_by"],
        }
        for d in await definitions(rt).summaries(team=current_team())
    ]
    if search:
        s = search.lower()
        rows = [r for r in rows if s in r["name"].lower() or s in r["workflowId"].lower()]
    facets: dict[str, dict[str, int]] = {"status": {}}
    for r in rows:
        facets["status"][r["status"]] = facets["status"].get(r["status"], 0) + 1
    wanted = request.query_params.getlist("status")
    # An archived workflow leaves the list unless asked for; the facet still counts it, so the filter can show it.
    rows = [r for r in rows if r["status"] in wanted] if wanted else [r for r in rows if r["status"] != "archived"]
    key = sort_by if sort_by in {"name", "updatedAt", "runs", "status", "version"} else "updatedAt"
    rows.sort(key=lambda r: r[key], reverse=sort_order == "desc")
    return ok({**page(rows, page_no, page_size), "facets": facets})


async def pending_requests(rt: Runtime) -> dict[str, dict[str, Any]]:
    """Open publish requests of v2 workflows, by workflow id."""
    rows = await agent_registry(rt).all_requests()
    return {r["subject_id"]: r for r in rows if r["kind"] == engine_lifecycle.KIND and r["status"] == "pending"}


def workflow_status(summary: dict[str, Any], request: dict[str, Any] | None) -> str:
    """The workflow's stage on a list row: archived once archived, the serving version's (live or paused) once one is
    approved, else in_review while a request is open, else draft."""
    if summary.get("archived_at"):
        return "archived"
    if summary["current_stage"]:
        return str(summary["current_stage"])
    return "in_review" if request is not None else "draft"


async def v2_workflow_rows(rt: Runtime, since: str) -> list[dict[str, Any]]:
    """Each v2 workflow as a row of the Workflows list (schemas.Workflow, `engine` v2), so the list joins both kinds on
    the server: steps are its nodes, gates its human reviews, the trigger its trigger node's type label; its status is
    the serving version's stage (live or paused), a draft before the first approval, and an open publish request is
    its `pendingPublish`, as for v1. Fields v2 has no counterpart for (agents, reviews, deployments) are empty."""
    out: list[dict[str, Any]] = []
    try:
        found = await definitions(rt).summaries(since=since, team=current_team())
    except DatabaseError as e:  # a database not yet migrated to the runner's tables lists v1 workflows alone
        log.warning("engine_definitions_unavailable", error=type(e).__name__)
        return []
    open_requests = await pending_requests(rt)
    for d in found:
        request = open_requests.get(d["workflow_id"])
        stored: dict[str, Any] = d["definition"] or {}
        nodes: list[dict[str, Any]] = list(stored.get("nodes") or [])
        types = [REGISTRY.find(str(n.get("type")), int(n.get("typeVersion") or 0)) for n in nodes]
        # The description says what starts it, as a v1 workflow's trigger text does; else the trigger node's type.
        trigger = str(stored.get("description") or "") or next(
            (t.label for t in types if t and t.group == "trigger"), ""
        )
        out.append(
            {
                "id": d["workflow_id"],
                "name": d["name"],
                "description": str(stored.get("description") or ""),
                "teamId": d["team_id"],
                "trigger": trigger,
                "agentSlugs": [],
                "stepCount": len(nodes),
                "gateCount": sum(1 for n in nodes if n.get("type") == HUMAN_REVIEW),
                "runs24h": d["recent"],
                "reviewed24h": d["reviewed"],
                "openReviews": d["open_reviews"],
                "status": workflow_status(d, request),
                "version": d["current_version"] or 0,
                "updatedAt": d["created_at"],
                "deploymentCount": 0,
                "kind": "standard",
                "engine": "v2",
                **(
                    {
                        "pendingPublish": {
                            "reviewId": request["id"],
                            "toVersion": request["version"],
                            "requestedBy": request["requested_by"],
                        }
                    }
                    if request
                    else {}
                ),
            }
        )
    return out


@router.delete("/definitions/{workflow_id}", status_code=204, response_model=None)
async def delete_definition(rt: Rt, me: Me, workflow_id: str) -> Response:
    """Deletes a draft (every version); a workflow that has run is kept, since its runs are pinned to its versions.
    403 unless the caller is a builder or admin of the owning team."""
    row = await definitions(rt).get(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    engine_lifecycle.require_rights(me, row, "delete")
    outcome = await definitions(rt).delete_draft(workflow_id, team=current_team())
    if outcome == "missing":
        raise NotFound(f"Workflow definition {workflow_id}")
    if outcome == "has_runs":
        raise Conflict(
            f"{workflow_id} has runs pinned to its versions, so it cannot be deleted.", code="definition_has_runs"
        )
    return Response(status_code=204)


@router.post("/definitions/{workflow_id}/archive", response_model=Envelope[DefinitionView])
async def archive_definition(rt: Rt, me: Me, workflow_id: str) -> JSONResponse:
    """Archives the workflow (c-274): it starts no run of any mode, a trigger no longer serves it, and it leaves the
    lists; its versions and runs are kept. Who may delete the workflow may archive it."""
    return ok(await _archived(rt, me, workflow_id, True))


@router.post("/definitions/{workflow_id}/restore", response_model=Envelope[DefinitionView])
async def restore_definition(rt: Rt, me: Me, workflow_id: str) -> JSONResponse:
    """Restores an archived workflow as it was: the version that served it serves again, live or paused."""
    return ok(await _archived(rt, me, workflow_id, False))


async def _archived(rt: Runtime, me: Principal, workflow_id: str, archived: bool) -> dict[str, Any]:
    row = await definitions(rt).get(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    engine_lifecycle.require_rights(me, row, "delete")
    await definitions(rt).set_archived(workflow_id, archived, by=me.email or me.sub, now=now_iso(), team=current_team())
    return await definition_view(rt, workflow_id)


class DefinitionShapes(Out):
    workflow_id: str
    version: int
    # Each step's output by the port it leaves by, as JSON Schema; `additionalProperties: false` is a closed shape.
    steps: dict[str, dict[str, dict[str, Any]]]


@router.get("/definitions/{workflow_id}/versions/{version}/shapes", response_model=Envelope[DefinitionShapes])
async def definition_shapes(rt: Rt, workflow_id: str, version: int) -> JSONResponse:
    """What each step of a saved version outputs, by port, before it has run (c-353): fixed by its type, built from
    its settings, or read from its document type or operation. A mapping picker reads it."""
    row = await definitions(rt).get(workflow_id, version, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id} version {version}")
    steps = await step_shapes.version_shapes(rt, current_team() or "", cast(dict[str, Any], row["definition"]))
    return ok({"workflowId": workflow_id, "version": version, "steps": steps})


@router.get("/definitions/{workflow_id}", response_model=Envelope[DefinitionView])
async def get_definition(rt: Rt, workflow_id: str, version: int | None = None) -> JSONResponse:
    return ok(await definition_view(rt, workflow_id, version))


async def definition_view(rt: Runtime, workflow_id: str, version: int | None = None) -> dict[str, Any]:
    store = definitions(rt)
    row = await store.get(workflow_id, version, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    request = await engine_lifecycle.pending(rt, workflow_id)
    current = await store.current(workflow_id, team=current_team())
    versions = [
        {
            "version": v["version"],
            "digest": v["digest"],
            "createdAt": v["created_at"],
            "createdBy": v["created_by"],
            "stage": engine_lifecycle.stage_of(v, request),
        }
        for v in await store.versions(workflow_id)
    ]
    review = request and {
        "id": request["id"],
        "version": request["version"],
        "requestedBy": request["requested_by"],
        "createdAt": request["created_at"],
    }
    return {
        "workflowId": workflow_id,
        "name": row["name"],
        "version": row["version"],
        "digest": row["digest"],
        "stage": engine_lifecycle.stage_of(row, request),
        "definition": row["definition"],
        "versions": versions,
        "liveVersion": current["version"] if current else None,
        "paused": bool(current and current["stage"] == "paused"),
        "review": review,
        "archivedAt": row.get("archived_at"),
    }


class DefinitionPublishInput(WireModel):
    # The draft to publish; the newest version when left out.
    version: int | None = None
    note: str = Field(default="", max_length=2000)


@router.post("/definitions/{workflow_id}/publish-requests", response_model=Envelope[PublishReview], status_code=201)
async def request_definition_publish(rt: Rt, me: Me, workflow_id: str, body: DefinitionPublishInput) -> JSONResponse:
    """Opens a publish request for a draft in Reviews; the version goes live when a second person approves it (at once
    under the dev auto-approve setting). 409 when the version is not a draft or a request is already open, 422 when it
    no longer passes its checks, 403 unless the caller is a builder or admin of the owning team (an admin for a
    workflow no team owns). The request lists what each step acts on: its operation, agent and approver."""
    return ok(await engine_lifecycle.request_publish(rt, me, workflow_id, body.version, body.note), status=201)


async def set_paused(rt: Runtime, me: Principal, workflow_id: str, paused: bool) -> dict[str, Any]:
    row = await definitions(rt).get(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    engine_lifecycle.require_rights(me, row, "pause" if paused else "resume")
    if await definitions(rt).set_paused(workflow_id, paused, team=current_team()) is None:
        raise Conflict(f"{workflow_id} has no live version to {'pause' if paused else 'resume'}.", code="not_live")
    return await definition_view(rt, workflow_id)


@router.post("/definitions/{workflow_id}/pause", response_model=Envelope[DefinitionView])
async def pause_definition(rt: Rt, me: Me, workflow_id: str) -> JSONResponse:
    """Stops new live runs of the workflow; runs under way keep going on their version. 409 before any is live; 403
    unless the caller is a builder or admin of the owning team (an admin for a workflow no team owns)."""
    return ok(await set_paused(rt, me, workflow_id, True))


@router.post("/definitions/{workflow_id}/resume", response_model=Envelope[DefinitionView])
async def resume_definition(rt: Rt, me: Me, workflow_id: str) -> JSONResponse:
    """Live runs start again on the live version. 409 before any is live; 403 as for pause."""
    return ok(await set_paused(rt, me, workflow_id, False))


class OptionView(Out):
    value: str
    label: str
    description: str


# How the mailbox picker names each kind of mailbox.
MAILBOX_KINDS = {"gmail": "Gmail", "imap": "IMAP", "graph": "Microsoft 365", "dev": "Dev folder"}

OptionSource: TypeAlias = Literal["agents", "tools", "workflows", "mailboxes"]  # noqa: UP040


@router.get("/option-sources", response_model=Envelope[list[OptionView]])
async def option_sources(rt: Rt, me: Me, source: OptionSource) -> JSONResponse:
    """The choices a node form offers for a field with an option source (`ui.fields.*.source`): published agents,
    registry operations, live v2 workflows, the acting team's mailboxes (Channels > Email). `steps` comes from
    the definition being edited; `knowledge` is not served yet, since no built node type reads a knowledge base."""
    options: list[dict[str, str]]
    if source == "mailboxes":
        # The team the caller acts in (X-Team-Id), also for a dev-password session, which reads across teams.
        found = await MailboxStore(rt.db).list(team=me.team_id) if me.team_id else []
        options = [
            {
                "value": m.address,
                "label": m.name or m.address,
                "description": f"{m.address} · {MAILBOX_KINDS[m.provider]}{' · paused' if m.paused else ''}",
            }
            for m in found
        ]
    elif source == "agents":
        agents = [a for a in await agent_registry(rt).rows() if a["published_version"] is not None]
        options = [
            {"value": a["id"], "label": a["slug"], "description": f"Published v{a['published_version']}"}
            for a in agents
        ]
    elif source == "tools":
        tools = [t for t in await known_tools(rt) if not str(t["id"]).startswith("workflow:")]
        options = [
            {"value": t["id"], "label": t["name"], "description": str(t.get("description") or "")} for t in tools
        ]
    else:
        live = [d for d in await definitions(rt).summaries(team=current_team()) if d["current_stage"] == "live"]
        options = [
            {"value": d["workflow_id"], "label": d["name"], "description": f"Live v{d['current_version']}"}
            for d in live
        ]
    return ok(sorted(options, key=lambda o: o["label"].lower()))


# ── Runs (workflow-runner.md section 5): the API only enqueues; a worker runs them. ──


runs_router = APIRouter(prefix="/v1/runs", dependencies=[Depends(principal)])
POLL_SECONDS = 0.25


class EngineRunInput(WireModel):
    workflow_id: str
    # The version to pin: the live version when left out, or the latest in test mode. A live run starts only on the
    # live version; test mode starts any version, a draft included.
    version: int | None = None
    input: dict[str, Any] = Field(default_factory=dict[str, Any])
    # The caller's key for what started the run; a repeated key returns the first run. A new key when left out.
    run_key: str | None = Field(default=None, max_length=200)
    mode: Literal["live", "test"] = "live"


class RunStarted(Out):
    run_id: str
    workflow_id: str
    version: int
    digest: str
    status: str
    # False when the run key had started a run already; that run is returned.
    created: bool


class RunWaiting(Out):
    node: str
    iteration: int
    payload: dict[str, Any]


class RunRow(Out):
    id: str
    # The display name of the workflow version the run is on, in the list; the id when it has none.
    workflow_name: str | None = None
    # Whether the caller may cancel it now: runs/cancel on an unfinished run (c-123).
    can_cancel: bool | None = None
    workflow_id: str
    version: int
    digest: str
    mode: str
    status: str
    outcome: str | None
    error: str | None
    input: dict[str, Any] | None
    output: Any
    waiting: RunWaiting | None
    created_by: str
    # Who or what started it, named: a person, a mailbox, another workflow's run, an agent or an API key.
    started_by: ActorView | None = None
    created_at: str
    updated_at: str
    finished_at: str | None


class StepAttempt(Out):
    attempt: int
    status: str
    effects: str
    key: str
    port: str | None
    input: Any
    output: Any
    error: str | None
    started_at: str
    finished_at: str | None


class EngineRunStep(Out):
    node_id: str
    iteration: int
    # The last attempt's: what the node returned, through which port, or its error.
    status: str
    port: str | None
    input: Any
    output: Any
    error: str | None
    attempts: list[StepAttempt]


class RunResult(Out):
    # The End step the run finished on, its name in the definition, the outcome it named and its output.
    node: str | None
    name: str | None
    outcome: str
    output: Any


class RunChild(Out):
    """A run a step started (Start workflow, once or for each item), with where it is now."""

    node_id: str
    index: int
    run_id: str
    status: str
    outcome: str | None


class RunFile(Out):
    id: str
    # The name the input gave it alongside the id (`{fileId, name}`), else files-service's; None when neither says.
    name: str | None


class RunDecision(Out):
    """A person's decision at a Human Task step: who, when and why, and the task it was made on."""

    node_id: str
    iteration: int
    # The Human Task's id, as Human Tasks lists it: the run, the step and its iteration.
    review_id: str
    action: str
    reason: str | None
    by: ActorView | None
    at: str | None


class RunDetail(RunRow):
    steps: list[EngineRunStep]
    # Set once the run reached an End, a failure End too: what that End returned.
    result: RunResult | None
    # The runs its steps started, in step and item order, each with its status (c-209's for each), read here so the
    # run page lists them without asking for each one.
    children: list[RunChild] = Field(default_factory=list[RunChild])
    # The files the run was given, in the order its input names them, so the run page links each by name.
    files: list[RunFile] = Field(default_factory=list[RunFile])
    # Each Human Task decided in this run, in step order, with the person named.
    decisions: list[RunDecision] = Field(default_factory=list[RunDecision])


def runs(rt: Runtime) -> RunStore:
    return RunStore(EngineTransactions(rt.db))


async def visible_run(rt: Runtime, run_id: str, me: Principal | None = None) -> dict[str, Any]:
    """The run, if the selected team may see it: the same team scoping as the run list, and for a scoped API key its
    own workflow's runs only (c-246). Another team's run is not found rather than forbidden, so its id reveals
    nothing."""
    run = await runs(rt).get(run_id)
    team = current_team()
    if run is None or (team is not None and run["team_id"] != team):
        raise NotFound("Run")
    if me is not None and (scope := key_scope(me)) is not None and scope != ("workflow", run["workflow_id"]):
        raise NotFound("Run")
    return run


def can_cancel(me: Principal, run: dict[str, Any]) -> bool:
    """runs/cancel for the caller on an unfinished run, by the rule the cancel route applies."""
    if run["status"] in ("succeeded", "failed", "cancelled"):
        return False
    try:
        require_runs_cancel(me, team_id=str(run["team_id"]), started_by=str(run["created_by"]), what="this run")
    except ApiError:
        return False
    return True


def run_view(r: dict[str, Any]) -> dict[str, Any]:
    waiting: dict[str, Any] | None = r.get("waiting")
    return {
        "id": r["id"],
        "workflowId": r["workflow_id"],
        "version": r["version"],
        "digest": r["digest"],
        "mode": r["mode"],
        "status": r["status"],
        "outcome": r["outcome"],
        "error": r["error"],
        "input": r["input"],
        "output": r["output"],
        "waiting": {k: waiting[k] for k in ("node", "iteration", "payload")} if waiting else None,
        "createdBy": r["created_by"],
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
        "finishedAt": r["finished_at"],
    }


def steps_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attempts grouped per node and iteration, in the order the steps started; each step shows its last attempt."""
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault((r["node_id"], r["iteration"]), []).append(r)
    out: list[dict[str, Any]] = []
    for (node, iteration), attempts in grouped.items():
        attempts.sort(key=lambda a: a["attempt"])
        last = attempts[-1]
        out.append(
            {
                "nodeId": node,
                "iteration": iteration,
                "status": last["status"],
                "port": last["port"],
                "input": redacted(last["input"]),
                "output": redacted(last["output"]),
                "error": last["error"],
                "attempts": [
                    {
                        "attempt": a["attempt"],
                        "status": a["status"],
                        "effects": a["effects"],
                        "key": a["key"],
                        "port": a["port"],
                        "input": redacted(a["input"]),
                        "output": redacted(a["output"]),
                        "error": a["error"],
                        "startedAt": a["started_at"],
                        "finishedAt": a["finished_at"],
                    }
                    for a in attempts
                ],
            }
        )
    return out


@runs_router.post(
    "",
    response_model=Envelope[RunStarted],
    status_code=202,
    responses={200: {"model": Envelope[RunStarted], "description": "The run key had started a run already"}},
)
async def start_engine_run(rt: Rt, me: Me, body: EngineRunInput) -> JSONResponse:
    """Writes the run and its start work row in one transaction and returns at once: a worker runs it. With no worker
    running the run stays queued. A live run is refused (409) unless it pins the live version: `not_live` before a
    version is approved or for another version, `workflow_paused` while the workflow is paused. An API key scoped to
    one workflow (c-246) starts that one only, on the version it pins when it pins one."""
    pinned = require_key_reaches(me, "workflow", body.workflow_id)
    if pinned is not None and body.version not in (None, pinned):
        raise Forbidden(f"This API key starts version {pinned} of {body.workflow_id} only.", code="key_target")
    version = body.version if pinned is None else pinned
    stored = await definitions(rt).get(body.workflow_id, version, team=current_team())
    if stored is None:
        what = f"version {version} of " if version is not None else ""
        raise NotFound(f"{what}workflow definition {body.workflow_id}")
    if body.mode == "test":
        # A test run tries any version, a draft included, which is a builder's step: a builder or admin of the team
        # that owns the workflow, or of the acting team for one no team owns, which every team runs. An API key never
        # starts one (require_builder refuses a caller with no role).
        require_builder(
            me,
            area="workflows",
            team_id=stored.get("team_id") or me.team_id,
            action="start a test run of",
            what=f"workflow {body.workflow_id}",
        )
    if body.mode == "live":
        # A builder or admin, or an API key of the team (c-122 Q1).
        require_runs_start(me, team_id=stored.get("team_id"), what=f"workflow {body.workflow_id}")
        stored = await live_version(definitions(rt), body.workflow_id, version, team=current_team())
    run, created = await start_run(
        runs(rt),
        stored,
        team_id=me.team_id,
        mode=body.mode,
        input=body.input,
        run_key=body.run_key,
        created_by=started_by(me),
    )
    data = {
        "runId": run["id"],
        "workflowId": run["workflow_id"],
        "version": run["version"],
        "digest": run["digest"],
        "status": run["status"],
        "created": created,
    }
    return ok(data, status=202 if created else 200)


class RunsQuery(BaseModel):
    workflowId: str | None = None  # noqa: N815 - the console's query parameter
    # The name the list took before it paged; kept so a caller written for it still filters.
    workflow_id: str | None = Field(default=None, json_schema_extra={"deprecated": True})
    status: list[str] = Field(default_factory=list[str])
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=25, ge=1, le=100)  # noqa: N815


@runs_router.get("", response_model=Envelope[ListResult[RunRow]])
async def list_engine_runs(rt: Rt, me: Me, q: Annotated[RunsQuery, Query()]) -> JSONResponse:
    """The selected team's runs, newest first, a page at a time; `status` repeats to keep several. `facets.status`
    counts the runs per status under the other filters. A scoped API key lists its own workflow's runs only."""
    wanted = q.workflowId or q.workflow_id
    if (scope := key_scope(me)) is not None:
        if scope[0] != "workflow" or wanted not in (None, scope[1]):
            return ok(paged([], 0, q.page, q.pageSize) | {"facets": {"status": {}}})
        wanted = scope[1]
    rows, total, by_status = await runs(rt).page(
        workflow_id=wanted,
        statuses=q.status,
        team_id=current_team(),
        offset=(q.page - 1) * q.pageSize,
        limit=q.pageSize,
    )
    who = await actors(rt, [started_by_of(r) for r in rows])
    views = [
        await for_people(rt, r, run_view(r))
        | {
            "canCancel": can_cancel(me, r),
            "workflowName": r.get("workflow_name"),
            "startedBy": who.get(started_by_of(r)),
        }
        for r in rows
    ]
    listed = paged(views, total, q.page, q.pageSize)
    return ok(listed | {"facets": {"status": by_status}})


@runs_router.get("/{run_id}", response_model=Envelope[RunDetail])
async def get_engine_run(rt: Rt, me: Me, run_id: str) -> JSONResponse:
    """The run with every step from the journal: per node its input, output, port, attempts and errors."""
    store = runs(rt)
    run = await visible_run(rt, run_id, me)
    steps = steps_view(await store.steps(run_id))
    decided = decisions_in(run_id, steps)
    names = await actors(rt, [d["by"] for d in decided if d["by"]])
    body = run_view(run) | {
        "steps": steps,
        "children": await started_runs(store, steps),
        "files": await named(rt, str(run["team_id"]), files_in(run["input"])),
        "decisions": [d | {"by": names.get(d["by"]) if d["by"] else None} for d in decided],
        "result": await run_result(rt, run, steps),
        "canCancel": can_cancel(me, run),
        "startedBy": (await actors(rt, [started_by_of(run)])).get(started_by_of(run)),
    }
    return ok(await for_people(rt, run, body))


# Where a run read carries what its steps worked on: the run's and each step's and attempt's input and output, an
# error's text, the values a decision carried and what a waiting step shows (payload). Ids, names and statuses around
# them are left alone (a run id's digits would read as an account number).
_VALUE_KEYS = frozenset({"input", "output", "error", "values", "payload"})


async def for_people(rt: Runtime, run: dict[str, Any], body: Any) -> Any:
    """`body`, read from `run`, as people see it (c-321): masked when the run's team has aiStepsMaskPersonalData on, the
    default. Every route that returns a run's or a step's values to a person answers through here."""
    return _values_masked(body) if await ai_steps_gate.people_see_masked(rt, run.get("team_id") or None) else body


def _values_masked(body: Any) -> Any:
    """The run as people read it with masking on (c-321): every value under _VALUE_KEYS, wherever it sits. The stored
    run keeps the real values the steps after them use."""
    if isinstance(body, dict):
        return {k: masked(v) if k in _VALUE_KEYS else _values_masked(v) for k, v in cast(dict[str, Any], body).items()}
    if isinstance(body, list):
        return [_values_masked(v) for v in cast(list[Any], body)]
    return body


def decisions_in(run_id: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The decided Human Task steps: a step whose output carries the person's `decision`, with when its last attempt
    finished; `by` stays raw for the caller to name."""
    out: list[dict[str, Any]] = []
    for s in steps:
        o = s.get("output")
        if s.get("status") != "ok" or not isinstance(o, dict):
            continue
        d = cast(dict[str, Any], o)
        if not isinstance(d.get("decision"), str):
            continue
        attempts = cast(list[dict[str, Any]], s.get("attempts") or [])
        finished = attempts[-1].get("finishedAt") if attempts else None
        out.append(
            {
                "nodeId": s["nodeId"],
                "iteration": s["iteration"],
                "reviewId": f"{run_id}:{s['nodeId']}:{s['iteration']}",
                "action": d["decision"],
                "reason": d.get("reason") if isinstance(d.get("reason"), str) else None,
                "by": str(d["by"]) if d.get("by") else None,
                "at": finished.isoformat() if isinstance(finished, datetime) else (str(finished) if finished else None),
            }
        )
    return out


FILE_ID = re.compile(r"fil_[0-9a-f]{32}")


def files_in(value: Any) -> list[dict[str, Any]]:
    """Every value in the input that is a file id, at any depth, once each and in order, with the name an upload gave
    beside it (`{fileId, name}`)."""
    found: dict[str, str | None] = {}

    def walk(v: Any, name: str | None = None) -> None:
        if isinstance(v, str):
            if FILE_ID.fullmatch(v):
                found[v] = found.get(v) or name
        elif isinstance(v, dict):
            d = cast(dict[str, Any], v)
            named = d.get("name") if isinstance(d.get("name"), str) else None
            for k, x in d.items():
                walk(x, named if k == "fileId" else None)
        elif isinstance(v, list):
            for x in cast(list[Any], v):
                walk(x)

    walk(value)
    return [{"id": i, "name": n} for i, n in found.items()]


async def started_runs(store: RunStore, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The runs the steps started, from each step's `runs` output (Start workflow), with their status now."""
    started: list[tuple[str, int, str]] = []
    for s in steps:
        out = s.get("output")
        listed = cast(list[Any], cast(dict[str, Any], out).get("runs") or []) if isinstance(out, dict) else []
        for i, r in enumerate(listed):
            if isinstance(r, dict) and cast(dict[str, Any], r).get("runId"):
                row = cast(dict[str, Any], r)
                started.append((str(s["nodeId"]), int(row.get("index", i)), str(row["runId"])))
    found = {r["id"]: r for r in await store.many([rid for _, _, rid in started])}
    return [
        {
            "nodeId": node,
            "index": index,
            "runId": rid,
            "status": found[rid]["status"],
            "outcome": found[rid].get("outcome"),
        }
        for node, index, rid in started
        if rid in found
    ]


async def run_result(rt: Runtime, run: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The run's result: the End node it finished on, from the pinned definition and the journal, with the outcome and
    output the worker recorded on the run."""
    if run["status"] == "cancelled" or run["outcome"] is None:
        return None
    stored = await definitions(rt).get(run["workflow_id"], run["version"])
    nodes = engine_lifecycle.nodes_of(stored["definition"] if stored else None)
    ends = [s for s in steps if nodes.get(s["nodeId"], {}).get("type") == "ops.flow.end" and s["status"] == "ok"]
    end = ends[-1]["nodeId"] if ends else None
    name = str(nodes[end].get("name") or end) if end else None
    return {"node": end, "name": name, "outcome": run["outcome"] or "done", "output": run["output"]}


@runs_router.post("/{run_id}/cancel", response_model=Envelope[RunRow])
async def cancel_engine_run(rt: Rt, me: Me, run_id: str) -> JSONResponse:
    """Cancels a run that has not ended: a queued run never starts, a waiting run's review leaves Reviews, a running
    pass finishes and journals the step under way and begins no other. Cancelling a cancelled run returns it; a run
    that succeeded or failed is refused (409)."""
    run = await visible_run(rt, run_id, me)
    require_runs_cancel(me, team_id=str(run["team_id"]), started_by=str(run["created_by"]), what=f"run {run_id}")
    if run["status"] == "cancelled":
        return ok(await for_people(rt, run, run_view(run)))
    cancelled, changed = await runs(rt).cancel(run_id, reason="by_user")
    if not changed or cancelled is None:
        raise Conflict(f"Run {run_id} has already {run['status']}.", code="run_finished")
    await runs(rt).settle_parents(cancelled)
    await EventLog(rt.db).append(
        thread_id=run_id, team_id=run["team_id"], run_id=run_id, type_="cancelled", node=None, data={"by": me.email}
    )
    return ok(await for_people(rt, cancelled, run_view(cancelled)))


async def event_frames(
    rt: Runtime, run_id: str, after: int, *, follow: bool, mask: bool = False
) -> AsyncGenerator[dict[str, str]]:
    log, store, cursor = EventLog(rt.db), runs(rt), after
    while True:
        batch = await log.run_events(run_id, run_id, cursor)
        for e in batch:
            cursor = e["seq"]
            shown = {**e, "data": masked(e.get("data"))} if mask else e
            yield {"id": str(e["seq"]), "event": e["type"], "data": json.dumps(shown, ensure_ascii=False)}
        if not follow:
            return
        run = await store.get(run_id)
        if not batch and (run is None or run["status"] in (*TERMINAL, "waiting")):
            return
        await asyncio.sleep(POLL_SECONDS)


@runs_router.get("/{run_id}/events", response_model=None, responses=SSE_RESPONSE)
async def engine_run_events(rt: Rt, me: Me, run_id: str, after: int = 0, follow: bool = True) -> EventSourceResponse:
    """The run's events with `seq` above `after`; the SSE `id` is the seq to resume from. With `follow` it keeps
    polling until the run ends or waits for a person."""
    run = await visible_run(rt, run_id, me)
    mask = await ai_steps_gate.people_see_masked(rt, run.get("team_id") or None)
    return EventSourceResponse(event_frames(rt, run_id, after, follow=follow, mask=mask), sep="\n", ping=15)
