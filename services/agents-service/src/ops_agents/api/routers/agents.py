"""/v1/agents: the console's agents contract (apps/console/src/lib/api/contract.ts, `agents`) over the registry.

Rows are the console's `Agent`; versions its `AgentVersion`; a publish request answers with its `Review`. Bulk routes
are not served.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import require_provisioner
from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.layout import required_tools
from ops_agent_kernel.types import ToolGrant, TurnRequest, TurnResult
from ops_agents.activities.agent_limits import AgentLimits, check_limits, limits_of
from ops_agents.activities.tool_directory import ToolsUnavailable, grants_for
from ops_agents.activities.tools import fill
from ops_agents.graphs.common import needs_step_up
from ops_contracts.chat import WireModel
from ops_service_kit.errors import ApiError, Conflict, ServiceUnavailable, Unprocessable, ValidationFailed
from ops_service_kit.http import Envelope, ListResult
from ops_service_kit.ids import new_id

from ...store.template_copies import TemplateCopies
from ..agent_registry import (
    GUARDRAILS,
    agent_review_body,
    agent_view,
    definition_of,
    go_live,
    registry,
    require_newest_draft,
    review_view,
    take_down,
    tasks_24h,
    version_state,
)
from ..auth import Principal, caller, caller_in, caller_of, principal, require_builder
from ..child_runs import engine_workflows, refusal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..guardrails import resolve_pins
from ..hitl_facade import page
from ..model_aliases import chat_aliases
from ..publish_policy import Decision, decide
from ..review_sla import sla_hours
from ..rights import rights
from ..schemas import (
    Agent,
    AgentRun,
    AgentTestTurn,
    AgentVersion,
    MemorySettings,
    PublishDecisionFields,
    PublishReview,
    WidgetSettings,
)
from ..skills import check_pins_hold
from ..team_names import team_name
from ..widgets import published as published_widget
from ..workflow_registry import registry as workflow_registry
from .tool_catalog import known_tools

# The provisioning service reaches list, read, create, change and delete with a team-scoped token (c-180); every other
# route takes a person or an API key (`Me`).
router = APIRouter(prefix="/v1/agents", dependencies=[Depends(caller_in("agents"))])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
Cl: TypeAlias = Annotated[Principal, Depends(caller)]  # noqa: UP040

Channel = Literal["voice", "chat", "email", "api"]


class Guardrails(WireModel):
    redact_pii: bool = True
    # Empty (None) is no cap; a number caps each turn. No ceiling: a real agent may need many.
    max_tool_calls_per_turn: int | None = Field(default=None, ge=1)
    # Empty here means the platform default of 50 model calls, never unlimited.
    max_model_calls_per_turn: int | None = Field(default=None, ge=1)
    # Per conversation (c-103): empty means the platform default (200 model calls, 5.00 cost), never unlimited.
    max_model_calls_per_conversation: int | None = Field(default=None, ge=1)
    max_cost_per_conversation: float | None = Field(default=None, gt=0)
    when_unsure: Literal["handoff", "ask", "decline"] = "handoff"
    blocked_topics: list[str] = Field(default_factory=list[str])


class AgentInput(WireModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=400)
    # A models-service alias; empty runs the agent on the runtime's alias.
    model: str = ""
    channels: list[Channel] = Field(default_factory=lambda: ["chat"])
    instructions: str | None = None
    # Set by the provisioning service only (c-180); a person sending either is refused.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class GuardrailPinInput(WireModel):
    guardrail_id: str
    # None or 0 on a new pin takes the published version.
    version: int | None = None
    # Off: saved on the version and never checked; callers cannot override it per chat or run.
    enabled: bool = True


class WidgetPinInput(WireModel):
    widget_id: str
    version: int | None = None


class AgentPatch(WireModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, min_length=1, max_length=400)
    model: str | None = None
    channels: list[Channel] | None = None
    instructions: str | None = None
    tool_ids: list[str] | None = None
    collections: list[str] | None = None
    guardrails: Guardrails | None = None
    # Guardrails attached by version (c-063): [{guardrailId, version}]; each saved with its version's rule.
    guardrail_pins: list[GuardrailPinInput] | None = None
    # What callers may override (c-068). Saved with the version and published through its review.
    limits: AgentLimits | None = None
    # Widgets by template (c-082): [{widgetId, version?}], each snapshotted from the library; version None takes the
    # latest published. Saved with the version and published through its review.
    widget_pins: list[WidgetPinInput] | None = None
    widgets: WidgetSettings | None = None
    # On or off, and which kinds (c-124).
    memory: MemorySettings | None = None
    note: str | None = None
    # Set by the provisioning service only (c-180).
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class PublishRequestInput(WireModel):
    version: int
    note: str = ""


class PausedInput(WireModel):
    paused: bool


class TestInput(WireModel):
    # No run-as: a test runs as the person testing (Run as was removed with c-285), so a field naming someone else
    # would be accepted and ignored.
    message: str = Field(min_length=1)


SORTS = {"name", "updatedAt", "tasks24h", "version", "teamId", "availability"}


async def _offered(rt: Runtime) -> set[str] | None:
    """The tool ids the directory offers now; None when tools-service cannot answer."""
    try:
        return {t["id"] for t in await known_tools(rt)}
    except ToolsUnavailable:
        return None


def _stale(tool_ids: list[str], offered: set[str] | None) -> list[str]:
    """Granted ids the directory no longer offers (unpublished, hidden, drifted or deleted). `workflow:` grants are
    judged by the workflow runner. Unknown when tools-service cannot answer: an agent page should not fail on it, so
    nothing is reported stale then."""
    if offered is None:
        return []
    return [t for t in tool_ids if not t.startswith("workflow:") and t not in offered]


def _agent_nodes(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """The agents a published v1 definition pins: each `agent_turn` node's snapshotted definition."""
    nodes = cast(list[dict[str, Any]], definition.get("nodes") or [])
    return [cast(dict[str, Any], n["config"]["agent"]) for n in nodes if n.get("kind") == "agent_turn"]


async def used_in_all(rt: Runtime) -> dict[str, list[dict[str, Any]]]:
    """By agent id, the workflows that run it: its own one-step workflow once published (`agent:<id>`, the one its
    deployments go through), v1 workflows whose published version pins it (at the version pinned then), drafts naming
    its slug, and v2 workflows whose latest version has an agent step on it, which runs the agent's published version.
    The agent page's Settings and Deployments tabs both read this list, so they agree on where the agent runs."""
    agents = await registry(rt).rows()
    by_slug = {r["slug"]: r for r in agents}
    published = {r["id"]: r["published_version"] for r in agents}
    out: dict[str, list[dict[str, Any]]] = {}
    for r in agents:
        if r["published_version"] is not None:
            use = {
                "workflowId": f"agent:{r['id']}",
                "workflowName": "Its own one-step workflow",
                "pinnedVersion": int(r["published_version"]),
                "status": "paused" if r["paused"] else "live",
                # Publishes with the agent, so it is never behind, never republished by hand, and deleting the agent
                # takes it too: callers leave it out of those (and workflowIds lists only other workflows).
                "own": True,
            }
            out.setdefault(str(r["id"]), []).append(use)

    def add(agent_id: str, workflow_id: str, name: str, version: int | None, status: str) -> None:
        if version is None or any(u["workflowId"] == workflow_id for u in out.get(agent_id, [])):
            return
        use = {"workflowId": workflow_id, "workflowName": name, "pinnedVersion": int(version), "status": status}
        out.setdefault(agent_id, []).append(use)

    assert rt.graph_store is not None
    for w in await workflow_registry(rt).rows():
        if w["status"] == "deleted":
            continue
        status = "paused" if w["status"] == "paused" else "live" if w["published_version"] is not None else "draft"
        if w["published_version"] is not None:
            v = await rt.graph_store.version(w["id"], int(w["published_version"]))
            for a in _agent_nodes(cast(dict[str, Any], v["definition"]) if v else {}):
                add(str(a["id"]), w["id"], w["name"], int(a["version"]), status)
        graph = cast(dict[str, Any], w.get("draft") or {})
        for node in cast(list[dict[str, Any]], graph.get("nodes") or []):
            data = cast(dict[str, Any], node.get("data") or {})
            if (slug := data.get("agentSlug")) and (row := by_slug.get(str(slug))):
                add(row["id"], w["id"], w["name"], published.get(row["id"]), "draft" if status == "draft" else status)
    for d in await engine_workflows(rt):
        definition = cast(dict[str, Any], d["definition"] or {})
        for node in cast(list[dict[str, Any]], definition.get("nodes") or []):
            params = cast(dict[str, Any], node.get("parameters") or {})
            if node.get("type") == "ops.ai.agent" and (aid := str(params.get("agent") or "")):
                add(aid, d["workflow_id"], d["name"], published.get(aid), "live")
    return out


async def _view(
    rt: Runtime,
    agent_id: str,
    tasks: dict[str, int] | None = None,
    offered: set[str] | None = None,
    used: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    reg = registry(rt)
    row = await reg.row(agent_id)
    spec = (await reg.version(agent_id, int(row["version"])))["spec"]
    counts = tasks if tasks is not None else await tasks_24h(rt)
    view = agent_view(row, spec, counts.get(agent_id, 0))
    view["staleToolIds"] = _stale(view["toolIds"], offered if offered is not None else await _offered(rt))
    uses = (used if used is not None else await used_in_all(rt)).get(agent_id, [])
    view["usedIn"] = sorted(uses, key=lambda u: u["workflowName"])
    view["workflowIds"] = sorted({u["workflowId"] for u in uses if not u.get("own")})
    view["templateId"], view["protection"] = row.get("template_id"), row.get("protection")
    return view


async def _checked_tools(rt: Runtime, tool_ids: list[str], granted: list[str]) -> list[str]:
    """The grants to save: a newly added id the directory does not offer is refused; one already granted that is no
    longer offered (stale) is dropped, so a stale grant never blocks saving the rest (c-048 T010)."""
    known = {t["id"] for t in await known_tools(rt)}
    # A workflow grant already held is kept while its workflow is paused or unpublished (it is simply not offered
    # until it is live again); a new one must be a workflow the directory offers now.
    offered = [t for t in tool_ids if t in known or (t.startswith("workflow:") and t in granted)]
    unknown = [t for t in tool_ids if t not in offered and t not in granted]
    for t in unknown:
        if t.startswith("workflow:") and (why := await refusal(rt, t.removeprefix("workflow:"))) is not None:
            raise ValidationFailed(f"{why.message} An agent cannot be granted it.", code=why.code)
    if unknown:
        raise ValidationFailed(f"Unknown tools: {', '.join(unknown)}.", code="unknown_tool")
    return offered


async def require_known_alias(rt: Runtime, alias: str) -> None:
    """Refuses a publish whose agent names an alias models-service does not serve; an empty alias uses the runtime's."""
    if not alias:
        return
    assert rt.model_aliases is not None
    known = await chat_aliases(rt.model_aliases)
    if alias not in known:
        raise Unprocessable(
            f"Model alias {alias} is not one models-service serves. Aliases: {', '.join(sorted(known))}.",
            code="unknown_model_alias",
        )


@router.get("", response_model=Envelope[ListResult[Agent]])
async def list_agents(
    *,
    request: Request,
    rt: Rt,
    page_no: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: str | None = None,
    sort_by: Annotated[str | None, Query(alias="sortBy")] = None,
    sort_order: Annotated[Literal["asc", "desc"], Query(alias="sortOrder")] = "asc",
    template_id: Annotated[str | None, Query(alias="templateId")] = None,
) -> JSONResponse:
    reg = registry(rt)
    tasks = await tasks_24h(rt)
    offered = await _offered(rt)
    used = await used_in_all(rt)
    held = [r for r in await reg.rows() if template_id is None or r.get("template_id") == template_id]
    rows = [await _view(rt, r["id"], tasks, offered, used) for r in held]
    if search:
        s = search.lower()
        rows = [a for a in rows if s in a["name"].lower() or s in a["role"].lower() or s in a["slug"]]
    facet_cols = ("availability", "teamId")
    facets: dict[str, dict[str, int]] = {c: {} for c in facet_cols}
    for a in rows:
        for c in facet_cols:
            facets[c][a[c]] = facets[c].get(a[c], 0) + 1
    for c in facet_cols:
        wanted = request.query_params.getlist(c)
        if wanted:
            rows = [a for a in rows if a[c] in wanted]
    key = sort_by if sort_by in SORTS else "name"
    rows.sort(key=lambda a: (a[key] is None, a[key]), reverse=sort_order == "desc")
    return ok({**page(rows, page_no, page_size), "facets": facets})


async def changeable(rt: Runtime, me: Principal, agent_id: str, action: str) -> dict[str, Any]:
    """The agent's row once the caller may change it (auth.require_builder: the roles grid, in the team that owns it or,
    for one no team owns, the team the request acts in)."""
    row = await registry(rt).row(agent_id)
    require_builder(
        me,
        area="agents",
        team_id=row["team_id"],
        action=action,
        what=f"agent {row['slug']}",
        protection=row.get("protection"),
    )
    return row


@router.post("", response_model=Envelope[Agent], status_code=201)
async def create_agent(rt: Rt, me: Cl, body: AgentInput) -> JSONResponse:
    require_builder(me, area="agents", team_id=me.team_id, action="create", what="an agent")
    if body.template_id is not None or body.protection is not None:
        require_provisioner(caller_of(me), "agents")
    spec: dict[str, Any] = {
        "name": body.name,
        "role": body.role,
        "model": body.model,
        "channels": body.channels,
        "instructions": body.instructions or f"You are {body.name}. {body.role}",
        "toolIds": [],
        "collections": [],
        "suggestions": [],
        "guardrails": GUARDRAILS,
    }
    aid = await registry(rt).create(
        spec, by=me.email, team_id=me.team_id, template_id=body.template_id, protection=body.protection
    )
    return ok(await _view(rt, aid), status=201)


@router.get("/{agent_id}", response_model=Envelope[Agent])
async def get_agent(rt: Rt, me: Cl, agent_id: str) -> JSONResponse:
    view = await _view(rt, agent_id)
    rights_of = await rights(lambda action: changeable(rt, me, agent_id, action))
    return ok({**view, **await team_name(rt, view.get("teamId")), **rights_of})


@router.patch("/{agent_id}", response_model=Envelope[Agent])
async def update_agent(rt: Rt, me: Cl, agent_id: str, body: AgentPatch) -> JSONResponse:
    """Saves the patched spec as a new draft version; what is live does not change until it is published."""
    reg = registry(rt)
    row = await changeable(rt, me, agent_id, "edit")
    if body.template_id is not None or body.protection is not None:
        require_provisioner(caller_of(me), "agents")
    spec = dict((await reg.version(agent_id, int(row["version"])))["spec"])
    patch = body.model_dump(
        exclude_none=True,
        exclude={
            "note",
            "guardrails",
            "guardrail_pins",
            "limits",
            "widget_pins",
            "widgets",
            "memory",
            "template_id",
            "protection",
        },
        by_alias=True,
    )
    if body.tool_ids is not None:
        patch["toolIds"] = await _checked_tools(rt, body.tool_ids, list(spec.get("toolIds") or []))
    if body.collections is not None:
        await _check_knowledge(rt, body.collections, list(spec.get("collections") or []))
    spec.update(patch)
    if body.guardrails is not None:
        spec["guardrails"] = body.guardrails.model_dump(by_alias=True)
    if body.tool_ids is not None or body.collections is not None:
        check_pins_hold(spec)
    if body.guardrail_pins is not None:
        wanted = [p.model_dump(by_alias=True) for p in body.guardrail_pins]
        spec["guardrailPins"] = await resolve_pins(rt, wanted, list(spec.get("guardrailPins") or []))
    if body.limits is not None:
        spec["limits"] = body.limits.wire()
    if body.widget_pins is not None:
        spec["widgetPins"] = await _widget_pins(rt, body.widget_pins)
    if body.widget_pins is not None or body.tool_ids is not None:
        _check_widget_tools(spec)
    if body.widgets is not None:
        spec["widgets"] = body.widgets.model_dump(by_alias=True)
    if body.memory is not None:
        spec["memory"] = body.memory.model_dump(by_alias=True)
    # Saved limits must still agree with the version: a changed model or a dropped tool without new limits is refused,
    # naming the limit, rather than leaving callers a choice the agent no longer has.
    if "limits" in spec:
        check_limits(limits_of(spec), spec)
    await reg.save(agent_id, spec, by=me.email, note=body.note or "")
    await reg.set_template(agent_id, template_id=body.template_id, protection=body.protection)
    return ok(await _view(rt, agent_id))


async def _check_knowledge(rt: Runtime, wanted: list[str], held: list[str]) -> None:
    """Each knowledge value a save adds is a knowledge base id kb-service knows (422 naming the rest): the runtime
    reads these as ids, so a name saved here would leave the agent citing nothing. Values the version already holds
    are kept even when their base is gone, so an agent stays saveable and the page shows them to remove (c-141).
    While kb-service cannot answer, a save that adds knowledge is refused (503) rather than accepted unchecked."""
    added = [k for k in wanted if k not in held]
    if not added:
        return
    known = {k.id for k in await rt.kbs().bases()}
    unknown = [k for k in added if k not in known]
    if unknown:
        raise Unprocessable(
            f"{', '.join(unknown)} {'is not a knowledge base' if len(unknown) == 1 else 'are not knowledge bases'}; "
            "pick knowledge bases from the list.",
            code="unknown_knowledge_base",
            details={"knowledgeBases": unknown},
        )


def _check_widget_tools(spec: dict[str, Any]) -> None:
    """Every tool a pinned widget's buttons ask for is one the version grants (422 naming it), so a widget never offers
    an action the agent cannot take; the same holds when a tool is taken away from an agent that pins such a widget."""
    granted = set(spec.get("toolIds") or [])
    for pin in cast(list[dict[str, Any]], spec.get("widgetPins") or []):
        missing = [t for t in required_tools(pin["tree"]) if t not in granted]
        if missing:
            raise Unprocessable(
                f"The {pin['name']} widget needs {', '.join(missing)}; grant {'it' if len(missing) == 1 else 'them'} "
                "first, or choose another widget.",
                code="widget_needs_tool",
                details={"widgetId": pin["widgetId"], "tools": missing},
            )


async def _widget_pins(rt: Runtime, wanted: list[WidgetPinInput]) -> list[dict[str, Any]]:
    """Each wanted template snapshotted from the registry or the seeded library, so the version keeps exactly the tree
    it was reviewed with. An unknown, unpublished or retired template or version is refused naming it (422)."""
    out: list[dict[str, Any]] = []
    for w in wanted:
        found = await published_widget(rt, w.widget_id, w.version)
        if found is None:
            at = f"{w.widget_id} v{w.version}" if w.version else w.widget_id
            raise Unprocessable(f"widgetPins: no published widget {at}.", code="unknown_widget")
        out.append(found.model_dump(by_alias=True, exclude={"sample"}))
    return out


@router.delete("/{agent_id}", status_code=204, response_model=None)
async def delete_agent(rt: Rt, me: Cl, agent_id: str) -> Response:
    await changeable(rt, me, agent_id, "delete")
    await registry(rt).delete(agent_id)
    take_down(rt, agent_id)
    await TemplateCopies(rt.db).removed_record("agent", agent_id)
    return Response(status_code=204)


@router.get("/{agent_id}/versions", response_model=Envelope[list[AgentVersion]])
async def list_versions(rt: Rt, agent_id: str) -> JSONResponse:
    reg = registry(rt)
    row = await reg.row(agent_id)
    requests = await reg.requests("agent", agent_id)
    pending = next((r for r in requests if r["status"] == "pending"), None)
    rejected = {int(r["version"]) for r in requests if r["status"] == "rejected"}
    asked = {int(r["version"]) for r in requests}
    out: list[dict[str, Any]] = []
    for v in await reg.versions(agent_id):
        n = int(v["version"])
        # History is what was published or put to a reviewer, plus the one draft (c-172); saves the per-save model
        # left behind are not listed.
        if not (v["published_at"] or n == row["version"] or n in asked):
            continue
        out.append(
            {
                "version": n,
                "note": v["note"],
                "changes": v["changes"],
                "current": n == row["published_version"],
                "state": version_state(row, n, pending, rejected),
                "savedAt": v["saved_at"],
                "savedBy": v["saved_by"],
                **({"publishedAt": v["published_at"], "publishedBy": v["published_by"]} if v["published_at"] else {}),
                **({"reviewId": v["review_id"]} if v["review_id"] else {}),
            }
        )
    return ok(out)


def _meta(thread: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], thread["meta"] or {})


@router.get("/{agent_id}/runs", response_model=Envelope[list[AgentRun]])
async def recent_runs(rt: Rt, agent_id: str, limit: Annotated[int, Query(ge=1, le=50)] = 10) -> JSONResponse:
    """The agent's newest threads in the selected team: chats with it and runs of its own `agent:<id>` graph."""
    await registry(rt).row(agent_id)
    assert rt.graph_store is not None
    own = await rt.graph_store.threads(f"agent:{agent_id}")
    chats = [t for t in await rt.graph_store.threads("agent_wrapper") if _meta(t).get("agentId") == agent_id]
    rows = sorted([*own, *chats], key=lambda t: str(t["created_at"]), reverse=True)[:limit]
    return ok(
        [
            {
                "threadId": t["id"],
                "kind": "chat" if t["graph"] == "agent_wrapper" else "graph",
                "title": str(_meta(t).get("title") or ""),
                "status": t["status"],
                **({"version": t["version"]} if t["version"] is not None else {}),
                "startedAt": t["created_at"],
                "updatedAt": t["updated_at"],
            }
            for t in rows
        ]
    )


@router.post("/{agent_id}/versions/{version}/restore", response_model=Envelope[Agent])
async def restore_version(rt: Rt, me: Me, agent_id: str, version: int) -> JSONResponse:
    """Copies a version into a new draft; nothing publishes."""
    reg = registry(rt)
    await changeable(rt, me, agent_id, "restore a version of")
    old = await reg.version(agent_id, version)
    await reg.save(agent_id, dict(old["spec"]), by=me.email, note=f"Restored from v{version}")
    return ok(await _view(rt, agent_id))


async def _publish_decision(rt: Runtime, agent_id: str, row: dict[str, Any], version: int) -> Decision:
    """What the team's publish policy says about publishing `version`; the preview and the publish both ask here, so
    the dialog never promises what the publish does not do."""
    reg = registry(rt)
    spec = (await reg.version(agent_id, version))["spec"]
    live = await reg.version(agent_id, int(row["published_version"])) if row["published_version"] else None
    return await decide(rt, area="agents", team_id=row["team_id"], old=live["spec"] if live else None, new=spec)


@router.get("/{agent_id}/publish-preview", response_model=Envelope[PublishDecisionFields])
async def publish_preview(rt: Rt, me: Me, agent_id: str, version: Annotated[int, Query()]) -> JSONResponse:
    """Whether publishing the newest draft would wait for review, and why; nothing is opened or changed."""
    row = await changeable(rt, me, agent_id, "publish")
    require_newest_draft(row, version)
    return ok((await _publish_decision(rt, agent_id, row, version)).record())


@router.post("/{agent_id}/publish-requests", response_model=Envelope[PublishReview], status_code=201)
async def request_publish(rt: Rt, me: Me, agent_id: str, body: PublishRequestInput) -> JSONResponse:
    """Opens an `agent_publish` review for the newest draft, or publishes it at once when the team's publish policy
    needs no review (`publish_preview` says which beforehand): its definition goes live and its graph compiles."""
    reg = registry(rt)
    row = await changeable(rt, me, agent_id, "publish")
    require_newest_draft(row, body.version)
    v = await reg.version(agent_id, body.version)
    spec = v["spec"]
    for alias in limits_of(spec).allowed_models:
        await require_known_alias(rt, alias)
    decision = await _publish_decision(rt, agent_id, row, body.version)
    approved = not decision.review_required
    review_body = {
        **agent_review_body(agent_id, spec, row, v, note=body.note, by=me.email),
        **decision.record(),
    }
    req = await reg.open_request(
        "agent", agent_id, body.version, note=body.note, by=me.email, body=review_body, approved=approved
    )
    if approved:
        await reg.publish(agent_id, body.version, by=req["decided_by"], review_id=req["id"])
        if not row["paused"]:
            go_live(rt, agent_id, body.version, spec)
    return ok(review_view(req, name=spec["name"], slug=row["slug"], sla_hours=await sla_hours(rt)), status=201)


@router.post("/{agent_id}/paused", response_model=Envelope[Agent])
async def set_paused(rt: Rt, me: Me, agent_id: str, body: PausedInput) -> JSONResponse:
    """Pausing stops new chats and new agent-graph threads; resuming serves the published version again. A builder or
    admin of the owning team pauses, as for a workflow (engine_lifecycle)."""
    reg = registry(rt)
    row = await changeable(rt, me, agent_id, "pause" if body.paused else "resume")
    published = row["published_version"]
    if body.paused and published is None:
        raise Conflict("This agent has never been published, so there is nothing to pause.", code="not_published")
    await reg.set_paused(agent_id, body.paused)
    if body.paused:
        take_down(rt, agent_id)
    elif published is not None:
        go_live(rt, agent_id, int(published), (await reg.version(agent_id, int(published)))["spec"])
    return ok(await _view(rt, agent_id))


def model_refusal(result: TurnResult) -> ApiError | None:
    """A turn the model endpoint refused answers with that refusal: 429 for a rate limit or budget, 403 for an alias
    not cleared for the data, 404 for an alias models-service no longer serves; anything else it refused is 503."""
    if result.error_status is None:
        return None
    error = ApiError(result.error or "The model call was refused.", code=result.error_code or "model_refused")
    error.status = result.error_status if result.error_status in (403, 404, 429) else 503
    return error


# Enough of a cited passage to recognise it in the test panel; the full text is in the knowledge base.
QUOTE_CHARS = 280


def _held(rt: Runtime, grant: ToolGrant) -> dict[str, Any]:
    """A tool the tested agent holds: whether a call pauses for a review (the kernel gates every grant that is not
    read-only or a workflow) and, from its approval template, at which gate and for whom."""
    tool = rt.catalog.tool(grant.name)
    tpl = tool.approval if tool else None
    out: dict[str, Any] = {"name": grant.name, "access": grant.access, "pauses": grant.gated}
    if grant.gated:
        out |= {"gate": tpl.gate if tpl else "Approval", "reviewers": tpl.reviewers if tpl else "a reviewer"}
    return out


@router.post("/{agent_id}/test", response_model=Envelope[AgentTestTurn])
async def test_agent(rt: Rt, me: Me, agent_id: str, body: TestInput) -> JSONResponse:
    """One kernel turn on the newest version, draft or not, with no thread kept: the single-turn harness API scripts
    and use cases drive. A write tool stops at its gate, so the reply says where production would pause instead of
    acting. The console tests on a real thread instead (POST /chat/threads with test: true, c-284 and c-285); this
    route goes once the use cases that call it move there (follow-up to c-285)."""
    if rt.ports is None:
        raise ServiceUnavailable(rt.model_error or "No model is configured.", code="model_unavailable")
    reg = registry(rt)
    row = await changeable(rt, me, agent_id, "test")
    defn = definition_of(agent_id, int(row["version"]), (await reg.version(agent_id, int(row["version"])))["spec"])
    req = TurnRequest(
        turn_id=new_id("turn"),
        run_id=new_id("run"),
        settings=rt.catalog.settings_for(defn, rt.settings.model_alias),
        tools=await grants_for(rt.directory(), list(defn.tools)),
        transcript=[],
        user_turn=body.message,
        kb_ids=defn.default_kb_ids,
    )
    started = time.perf_counter()
    result: TurnResult | None = None
    async for event in run_turn(req, rt.ports):
        if isinstance(event, TurnFinished):
            result = event.result
    assert result is not None
    if (refused := model_refusal(result)) is not None:
        raise refused
    # Named as kb-service names them, never from the agents seed; while it is down, by id.
    try:
        kb_names = {k.id: k.name for k in await rt.kbs().bases()} if req.kb_ids or result.citations else {}
    except ApiError:
        kb_names = {}
    out: dict[str, Any] = {
        "reply": result.text,
        "toolCalls": [
            {
                "name": c.tool,
                "input": str(c.input),
                "output": "" if c.output is None else str(c.output),
                "status": c.status,
                "access": c.access,
            }
            for c in result.tool_calls
        ],
        "citations": [
            {
                "source": c.passage.title,
                "section": c.passage.section,
                "kbId": c.passage.kb_id,
                "kbName": kb_names.get(c.passage.kb_id, c.passage.kb_id),
                "page": c.passage.page,
                "quote": c.passage.text[:QUOTE_CHARS],
            }
            for c in result.citations
        ],
        "tookMs": round((time.perf_counter() - started) * 1000),
        "model": req.settings.model_alias,
        "knowledgeBases": [{"id": k, "name": kb_names.get(k, k)} for k in req.kb_ids],
        "tools": [_held(rt, g) for g in req.tools],
        "skills": result.skills,
        "guardrails": [{"name": g.get("name"), "version": g.get("version")} for g in result.guardrails_checked],
        "searched": bool(req.kb_ids),
    }
    fired = result.guardrail if result.stop_reason == "guardrail" else None
    if fired is not None and fired.get("when") in ("before", "after"):
        out["blockedBy"] = {"name": fired["name"], "topic": fired["topic"], "when": fired["when"]}
        if fired["when"] == "before":
            # Refused on the question: the kernel searches and loads only after that check, and the model never ran.
            out |= {"searched": False, "skills": []}
    if result.interrupt is not None:
        # Built as the agent graph's approval node builds the review a real run opens, so the panel shows that review.
        call = result.interrupt.pending_call
        tool = rt.catalog.tool(call.tool)
        tpl = tool.approval if tool else None
        values = {k: str(v) for k, v in call.input.items()}
        out["wouldPause"] = {
            "gate": tpl.gate if tpl else result.interrupt.needed,
            "reviewers": tpl.reviewers if tpl else "a reviewer",
            "tool": call.tool,
            "action": fill(tpl.action, values) if tpl else result.interrupt.needed,
            "stepUp": await needs_step_up(rt.graph_deps, call.tool) if rt.graph_deps else False,
        }
    return ok(out)
