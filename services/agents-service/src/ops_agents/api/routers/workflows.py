"""/v1/workflows: the console's workflows contract (apps/console/src/lib/api/contract.ts, `workflows`) over the
workflow registry. Rows are the console's `Workflow`; a detail adds the live graph and the draft. Bulk routes are not
served. A workflow's id is its graph name: `POST /v1/threads {graph: <id>}` starts it on its pointer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import Field

from ops_access import can
from ops_agents.graphs.definition import ROUTE_OP_LABELS, compile_definition, route_field_types
from ops_contracts.chat import WireModel
from ops_identity import CurrentTenantCaller
from ops_service_kit.errors import Conflict, NotFound, ServiceUnavailable, Unprocessable, ValidationFailed
from ops_service_kit.http import Envelope, ListResult
from ops_service_kit.ids import new_id, now_iso

from ..agent_registry import registry as agent_registry
from ..agent_registry import review_view
from ..auth import Principal, principal, require_builder
from ..deps import Runtime, runtime
from ..envelope import ok
from ..hitl_facade import page
from ..publish_policy import decide
from ..review_sla import sla_hours
from ..rights import rights
from ..schemas import (
    PublishReview,
    RouteVocabulary,
    ValidationRun,
    Version,
    Workflow,
    WorkflowDetail,
    WorkflowDraft,
    WorkflowRef,
    WorkflowRun,
    WorkflowTestRun,
)
from ..team_names import team_name
from ..workflow_registry import (
    agent_pins,
    compile_graph,
    counts_24h,
    new_row,
    publish,
    registry,
    run_rows,
    template_graph,
    workflow_view,
)
from . import engine

router = APIRouter(prefix="/v1/workflows", dependencies=[Depends(principal)])
# For other services (tools-service's approvals): an Ed25519 service token for audience "agents" naming the tenant.
refs_router = APIRouter(prefix="/v1/workflow-refs")
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

# A test run answers each pause with an approval; a graph that pauses more often than this is looping.
MAX_TEST_PAUSES = 5


class WorkflowInput(WireModel):
    name: str = Field(min_length=1, max_length=200)
    trigger: str = "Manual"
    template: Literal["blank", "approval", "triage", "chat"] = "blank"
    agent_slug: str | None = None


class GraphBody(WireModel):
    graph: dict[str, Any]


class ValidateInput(WireModel):
    graph: dict[str, Any]
    target: Literal["draft", "live"] = "draft"


class PublishInput(WireModel):
    graph: dict[str, Any]
    note: str = ""
    validation_run_id: str | None = None
    checks_failing: int = 0


class SettingsInput(WireModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    trigger: str | None = None


class StatusInput(WireModel):
    status: Literal["live", "draft", "paused"]


class PointerInput(WireModel):
    version: int


class TestInput(WireModel):
    """The sample case: the email a definition's nodes read (`WorkflowState.email`)."""

    email: dict[str, Any] = Field(
        default_factory=lambda: {
            "sender": "test@example.com",
            "subject": "Test",
            "body": "A test case.",
            "attachments": [],
        }
    )
    graph: dict[str, Any] | None = None


async def _view(
    rt: Runtime, workflow_id: str, counts: tuple[dict[str, int], dict[str, int]] | None = None
) -> dict[str, Any]:
    reg = registry(rt)
    row = await reg.row(workflow_id)
    versions = await reg.versions(workflow_id)
    live = next((v for v in versions if v["version"] == row["published_version"]), None)
    pending = next(
        (r for r in await agent_registry(rt).requests("workflow", workflow_id) if r["status"] == "pending"), None
    )
    runs, waiting = counts or await counts_24h(rt)
    return workflow_view(row, live, pending, runs.get(workflow_id, 0), waiting.get(workflow_id, 0))


async def _detail(rt: Runtime, workflow_id: str) -> dict[str, Any]:
    reg = registry(rt)
    row = await reg.row(workflow_id)
    versions = await reg.versions(workflow_id)
    live = next((v for v in versions if v["version"] == row["published_version"]), None)
    graph: dict[str, Any] = (live["graph"] if live else row["draft"]) or {"nodes": [], "edges": []}
    out: dict[str, Any] = {**await _view(rt, workflow_id), "graph": {"workflowId": workflow_id, **graph}}
    if row["draft"] is not None:
        out["draft"] = {
            "graph": {"workflowId": workflow_id, **row["draft"]},
            "savedAt": row["draft_saved_at"],
            "savedBy": row["draft_saved_by"],
        }
    return out


def _graph(raw: dict[str, Any]) -> dict[str, Any]:
    """The nodes and edges of a console graph; the console's workflowId and emailConfig are not part of it."""
    return {"nodes": raw.get("nodes") or [], "edges": raw.get("edges") or []}


@router.get("", response_model=Envelope[ListResult[Workflow]])
async def list_workflows(
    *,
    request: Request,
    rt: Rt,
    page_no: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: str | None = None,
    sort_by: Annotated[str | None, Query(alias="sortBy")] = None,
    sort_order: Annotated[Literal["asc", "desc"], Query(alias="sortOrder")] = "asc",
) -> JSONResponse:
    counts = await counts_24h(rt)
    rows = [await _view(rt, r["id"], counts) for r in await registry(rt).rows()]
    # v2 runner definitions join here, so the console lists both kinds from one page of one request.
    since = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    rows += await engine.v2_workflow_rows(rt, since)
    if search:
        s = search.lower()
        rows = [w for w in rows if s in w["name"].lower() or s in w["description"].lower()]
    facets: dict[str, dict[str, int]] = {"status": {}}
    for w in rows:
        facets["status"][w["status"]] = facets["status"].get(w["status"], 0) + 1
    wanted = request.query_params.getlist("status")
    # An archived workflow leaves the list unless asked for; the facet still counts it, so the filter can show it.
    rows = [w for w in rows if w["status"] in wanted] if wanted else [w for w in rows if w["status"] != "archived"]
    key = sort_by if sort_by in {"name", "updatedAt", "runs24h", "status", "version"} else "name"
    rows.sort(key=lambda w: w[key], reverse=sort_order == "desc")
    return ok({**page(rows, page_no, page_size), "facets": facets})


async def changeable(rt: Runtime, me: Principal, workflow_id: str, action: str) -> dict[str, Any]:
    """The workflow's row once the caller may change it (auth.require_builder: the roles grid, in the team that owns
    it or, for one no team owns, the team the request acts in)."""
    row = await registry(rt).row(workflow_id)
    require_builder(
        me,
        area="workflows",
        team_id=row["team_id"],
        action=action,
        what=f"workflow {row['name']}",
    )
    return row


@router.post("", response_model=Envelope[Workflow], status_code=201)
async def create_workflow(rt: Rt, me: Me, body: WorkflowInput) -> JSONResponse:
    """Creates the row with the template's graph as its draft. The id is a new graph name."""
    require_builder(me, area="workflows", team_id=me.team_id, action="create", what="a workflow")
    if body.template == "chat" and not body.agent_slug:
        raise ValidationFailed("The chat template needs agentSlug.", code="agent_required")
    wid = new_id("wf")
    draft = template_graph(body.template, body.trigger, body.agent_slug)
    await registry(rt).create(new_row(wid, body.name, body.trigger, team_id=me.team_id, draft=draft, by=me.email))
    return ok(await _view(rt, wid), status=201)


@router.get("/route-fields", response_model=Envelope[RouteVocabulary])
async def route_fields() -> JSONResponse:
    """What a branch's route may compare (`data.routes`): the fields with their types, and the operators with the
    types each applies to. The same lists the definition's validation enforces."""
    fields = [{"name": n, "type": t} for n, t in route_field_types().items()]
    ops = [
        {"op": op, "label": label, "types": list(types), **({"list": True} if op == "in" else {})}
        for op, (label, types) in ROUTE_OP_LABELS.items()
    ]
    return ok({"fields": fields, "ops": ops})


@router.get("/{workflow_id}", response_model=Envelope[WorkflowDetail])
async def get_workflow(rt: Rt, me: Me, workflow_id: str) -> JSONResponse:
    detail = await _detail(rt, workflow_id)
    rights_of = await rights(lambda action: changeable(rt, me, workflow_id, action))
    return ok({**detail, **await team_name(rt, detail.get("teamId")), **rights_of})


@router.patch("/{workflow_id}", response_model=Envelope[Workflow])
async def update_settings(rt: Rt, me: Me, workflow_id: str, body: SettingsInput) -> JSONResponse:
    await changeable(rt, me, workflow_id, "edit")
    values = body.model_dump(exclude_none=True)
    if values:
        await registry(rt).update(workflow_id, **values)
    return ok(await _view(rt, workflow_id))


@router.delete("/{workflow_id}", status_code=204, response_model=None)
async def delete_workflow(rt: Rt, me: Me, workflow_id: str) -> Response:
    """Marks the row deleted: it leaves the list and new threads refuse the id; threads already running keep going."""
    await changeable(rt, me, workflow_id, "delete")
    await registry(rt).delete(workflow_id)
    return Response(status_code=204)


@router.put("/{workflow_id}/draft", response_model=Envelope[WorkflowDraft])
async def save_draft(rt: Rt, me: Me, workflow_id: str, body: GraphBody) -> JSONResponse:
    await changeable(rt, me, workflow_id, "save")
    at = now_iso()
    await registry(rt).update(workflow_id, draft=_graph(body.graph), draft_saved_at=at, draft_saved_by=me.email)
    return ok({"graph": {"workflowId": workflow_id, **_graph(body.graph)}, "savedAt": at, "savedBy": me.email})


@router.delete("/{workflow_id}/draft", response_model=Envelope[None])
async def discard_draft(rt: Rt, me: Me, workflow_id: str) -> JSONResponse:
    await changeable(rt, me, workflow_id, "discard the draft of")
    await registry(rt).update(workflow_id, draft=None, draft_saved_at=None, draft_saved_by=None)
    return ok(None)


@router.post("/{workflow_id}/validate", response_model=Envelope[ValidationRun])
async def validate_graph(rt: Rt, me: Me, workflow_id: str, body: ValidateInput) -> JSONResponse:
    """Compiles the graph and records each check as a result: the node catalogue, agent pins (each agent step must
    name a published agent), one trigger, reachability, and the definition's own validation. Advisory: it blocks
    nothing; a publish compiles again."""
    await changeable(rt, me, workflow_id, "validate")
    compiled = compile_graph(workflow_id, _graph(body.graph), await agent_pins(rt))
    results = [c.result() for c in compiled.checks]
    passed = sum(1 for c in compiled.checks if c.passed)
    run = {
        "id": new_id("val"),
        "workflow_id": workflow_id,
        "ran_at": now_iso(),
        "target": body.target,
        "results": results,
        "summary": {"passed": passed, "total": len(results), "regressions": 0, "checksFailing": compiled.failing},
    }
    await registry(rt).save_validation(run)
    return ok(_validation_view(run))


def _validation_view(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run["id"],
        "workflowId": run["workflow_id"],
        "ranAt": run["ran_at"],
        "target": run["target"],
        "results": run["results"],
        "summary": run["summary"],
    }


@router.get("/{workflow_id}/validations/latest", response_model=Envelope[ValidationRun | None])
async def last_validation(rt: Rt, workflow_id: str) -> JSONResponse:
    await registry(rt).row(workflow_id)
    run = await registry(rt).last_validation(workflow_id)
    return ok(_validation_view(run) if run else None)


@router.post("/{workflow_id}/test", response_model=Envelope[WorkflowTestRun])
async def test_run(rt: Rt, me: Me, workflow_id: str, body: TestInput) -> JSONResponse:
    """Runs the draft (or the given graph) once on the sample email, in memory: no thread is kept, and each pause is
    answered with an approval so the run goes to its end."""
    if rt.graph_deps is None:
        raise ServiceUnavailable(rt.model_error or "No model is configured.", code="model_unavailable")
    row = await changeable(rt, me, workflow_id, "test")
    graph = _graph(body.graph or row["draft"] or {})
    compiled = compile_graph(workflow_id, graph, await agent_pins(rt))
    if compiled.definition is None:
        raise Unprocessable(
            "The graph does not compile.",
            code="checks_failing",
            details={"checks": [c.result() for c in compiled.checks if not c.passed]},
        )
    graph_run: Any = compile_definition(compiled.definition, rt.graph_deps, InMemorySaver())
    config: Any = {"configurable": {"thread_id": new_id("wft")}}
    pauses = 0
    values = await graph_run.ainvoke({"email": body.email}, config)
    while (await graph_run.aget_state(config)).next and pauses < MAX_TEST_PAUSES:
        pauses += 1
        values = await graph_run.ainvoke(Command(resume={"decision": "approved", "reason": "test run"}), config)
    finished = not (await graph_run.aget_state(config)).next
    return ok(
        {
            "status": "completed" if finished else "stopped",
            "pausesApproved": pauses,
            "visited": [v.split("@")[0] for v in values.get("visited", [])],
            "output": values.get("draft"),
            "endStatus": values.get("status"),
        }
    )


@router.post("/{workflow_id}/publish-requests", response_model=Envelope[PublishReview], status_code=201)
async def request_publish(rt: Rt, me: Me, workflow_id: str, body: PublishInput) -> JSONResponse:
    """Compiles the graph to a definition and opens a `publish_request` review. Approved at once under the dev
    auto-approve setting, which publishes it: a graph version with its digest, and the pointer moved to it."""
    row = await changeable(rt, me, workflow_id, "publish")
    graph = _graph(body.graph)
    compiled = compile_graph(workflow_id, graph, await agent_pins(rt))
    if compiled.definition is None:
        raise Unprocessable(
            "The graph does not compile; validate it to see the failing checks.",
            code="checks_failing",
            details={"checks": [c.result() for c in compiled.checks if not c.passed]},
        )
    versions = await registry(rt).versions(workflow_id)
    live = next((v["graph"] for v in versions if v["version"] == row["published_version"]), None)
    decision = await decide(rt, area="workflows", team_id=row["team_id"], old=live, new=graph)
    approved = not decision.review_required
    passed = sum(1 for c in compiled.checks if c.passed)
    info: dict[str, Any] = {
        "workflowId": workflow_id,
        "fromVersion": row["published_version"] or 0,
        "toVersion": (versions[0]["version"] + 1) if versions else 1,
        "note": body.note,
        "requestedBy": me.email,
        "changes": [],
        "validation": {"passed": passed, "total": len(compiled.checks), "regressions": 0, "checksFailing": 0},
        "digest": compiled.definition.digest(),
        # What a later decision publishes: the definition as compiled now, with the agent pins the reviewer saw.
        "definition": compiled.definition.model_dump(mode="json"),
        "graph": graph,
        **decision.record(),
    }
    req = await agent_registry(rt).open_request(
        "workflow", workflow_id, info["toVersion"], note=body.note, by=me.email, body=info, approved=approved
    )
    if approved:
        version = await publish(
            rt, workflow_id, compiled.definition, graph, note=body.note, by=req["decided_by"], review_id=req["id"]
        )
        req = {**req, "version": version, "body": {**info, "toVersion": version}}
    return ok(review_view(req, name=row["name"], slug="", sla_hours=await sla_hours(rt)), status=201)


@router.post("/{workflow_id}/status", response_model=Envelope[Workflow])
async def set_status(rt: Rt, me: Me, workflow_id: str, body: StatusInput) -> JSONResponse:
    row = await changeable(rt, me, workflow_id, "change the status of")
    if body.status == "live" and row["published_version"] is None:
        raise Conflict("Publish this workflow before setting it live.", code="not_published")
    await registry(rt).update(workflow_id, status=body.status)
    return ok(await _view(rt, workflow_id))


@router.get("/{workflow_id}/versions", response_model=Envelope[list[Version]])
async def list_versions(rt: Rt, workflow_id: str) -> JSONResponse:
    row = await registry(rt).row(workflow_id)
    return ok(
        [
            {
                "version": v["version"],
                "publishedAt": v["published_at"],
                "publishedBy": v["published_by"],
                "note": v["note"],
                "changes": v["changes"],
                "current": v["version"] == row["published_version"],
            }
            for v in await registry(rt).versions(workflow_id)
        ]
    )


@router.post("/{workflow_id}/versions/{version}/restore", response_model=Envelope[Workflow])
async def restore_version(rt: Rt, me: Me, workflow_id: str, version: int) -> JSONResponse:
    """Copies a published version's graph into the draft; nothing publishes."""
    await changeable(rt, me, workflow_id, "restore a version of")
    v = next((v for v in await registry(rt).versions(workflow_id) if v["version"] == version), None)
    if v is None:
        raise NotFound(f"Workflow {workflow_id} version {version}")
    await registry(rt).update(workflow_id, draft=v["graph"], draft_saved_at=now_iso(), draft_saved_by=me.email)
    return ok(await _view(rt, workflow_id))


@router.post("/{workflow_id}/pointer", response_model=Envelope[Workflow])
async def move_pointer(rt: Rt, me: Me, workflow_id: str, body: PointerInput) -> JSONResponse:
    """Points new threads at an already-published version, for a rollback; running threads keep theirs."""
    await changeable(rt, me, workflow_id, "roll back")
    if not any(v["version"] == body.version for v in await registry(rt).versions(workflow_id)):
        raise NotFound(f"Workflow {workflow_id} version {body.version}")
    await registry(rt).update(workflow_id, published_version=body.version)
    return ok(await _view(rt, workflow_id))


@router.get("/{workflow_id}/runs", response_model=Envelope[ListResult[WorkflowRun]])
async def list_runs(
    *,
    request: Request,
    rt: Rt,
    workflow_id: str,
    page_no: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
) -> JSONResponse:
    await registry(rt).row(workflow_id)
    rows = await run_rows(rt, workflow_id)
    facets: dict[str, dict[str, int]] = {"status": {}}
    for r in rows:
        facets["status"][r["status"]] = facets["status"].get(r["status"], 0) + 1
    if wanted := request.query_params.getlist("status"):
        rows = [r for r in rows if r["status"] in wanted]
    return ok({**page(rows, page_no, page_size), "facets": facets})


@refs_router.get("", response_model=Envelope[list[WorkflowRef]])
async def workflow_refs(rt: Rt, caller: CurrentTenantCaller) -> JSONResponse:
    """Workflows by id, name and owning team: every one for a service holding `workflows:view` that governs calls on
    their behalf (c-168), the team's for a person with workflows.view (c-222). The registry is not yet partitioned by
    tenant (identity-and-tenancy.md); the route still requires a tenant, so callers key what they keep by it."""
    team = None if caller.kind == "service" else caller.team_id
    can(caller, "workflows", "view", team=team, what="the workflow list")
    rows = [r for r in await registry(rt).rows() if team is None or r["team_id"] == team]
    return ok([{"id": r["id"], "name": r["name"], "teamId": r["team_id"], "status": r["status"]} for r in rows])
