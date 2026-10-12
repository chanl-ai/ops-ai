"""/v1/agents: the console's agents contract (apps/console/src/lib/api/contract.ts, `agents`) over the registry.

Rows are the console's `Agent`; versions its `AgentVersion`; a publish request answers with its `Review`. Bulk routes
are not served.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.types import TurnRequest, TurnResult
from ops_contracts.chat import WireModel
from ops_service_kit.errors import ApiError, Conflict, ServiceUnavailable, Unprocessable, ValidationFailed
from ops_service_kit.ids import new_id

from ..agent_registry import (
    GUARDRAILS,
    agent_view,
    auto_approves,
    definition_of,
    go_live,
    registry,
    require_newest_draft,
    review_view,
    take_down,
    tasks_24h,
    version_state,
)
from ..auth import Principal, principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..hitl_facade import page
from ..model_aliases import chat_aliases
from ..schemas import Agent, AgentTestTurn, AgentVersion, Envelope, ListResult, PublishReview
from .tool_catalog import known_tools

router = APIRouter(prefix="/v1/agents", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

Channel = Literal["voice", "chat", "email", "api"]


class Guardrails(WireModel):
    redact_pii: bool = True
    max_tool_calls_per_turn: int = Field(default=6, ge=1, le=20)
    when_unsure: Literal["handoff", "ask", "decline"] = "handoff"
    blocked_topics: list[str] = Field(default_factory=list[str])


class AgentInput(WireModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=400)
    # A models-service alias; empty runs the agent on the runtime's alias.
    model: str = ""
    owner: str = "Operations"
    channels: list[Channel] = Field(default_factory=lambda: ["chat"])
    instructions: str | None = None


class AgentPatch(WireModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, min_length=1, max_length=400)
    model: str | None = None
    owner: str | None = None
    channels: list[Channel] | None = None
    instructions: str | None = None
    tool_ids: list[str] | None = None
    collections: list[str] | None = None
    guardrails: Guardrails | None = None
    note: str | None = None


class PublishRequestInput(WireModel):
    version: int
    note: str = ""


class PausedInput(WireModel):
    paused: bool


class TestInput(WireModel):
    message: str = Field(min_length=1)
    run_as_id: str | None = None


SORTS = {"name", "updatedAt", "tasks24h", "version", "owner", "availability"}


async def _view(rt: Runtime, agent_id: str, tasks: dict[str, int] | None = None) -> dict[str, Any]:
    reg = registry(rt)
    row = await reg.row(agent_id)
    spec = (await reg.version(agent_id, int(row["version"])))["spec"]
    counts = tasks if tasks is not None else await tasks_24h(rt)
    return agent_view(row, spec, counts.get(agent_id, 0))


def _check_tools(rt: Runtime, tool_ids: list[str]) -> None:
    known = {t["id"] for t in known_tools(rt)}
    unknown = [t for t in tool_ids if t not in known]
    if unknown:
        raise ValidationFailed(f"Unknown tools: {', '.join(unknown)}.", code="unknown_tool")


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
) -> JSONResponse:
    reg = registry(rt)
    tasks = await tasks_24h(rt)
    rows = [await _view(rt, r["id"], tasks) for r in await reg.rows()]
    if search:
        s = search.lower()
        rows = [a for a in rows if s in a["name"].lower() or s in a["role"].lower() or s in a["slug"]]
    facet_cols = ("availability", "owner")
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


@router.post("", response_model=Envelope[Agent], status_code=201)
async def create_agent(rt: Rt, me: Me, body: AgentInput) -> JSONResponse:
    spec: dict[str, Any] = {
        "name": body.name,
        "role": body.role,
        "model": body.model,
        "owner": body.owner,
        "channels": body.channels,
        "instructions": body.instructions or f"You are {body.name}. {body.role}",
        "toolIds": [],
        "collections": [],
        "suggestions": [],
        "guardrails": GUARDRAILS,
    }
    aid = await registry(rt).create(spec, by=me.email, team_id=me.team_id)
    return ok(await _view(rt, aid), status=201)


@router.get("/{agent_id}", response_model=Envelope[Agent])
async def get_agent(rt: Rt, agent_id: str) -> JSONResponse:
    return ok(await _view(rt, agent_id))


@router.patch("/{agent_id}", response_model=Envelope[Agent])
async def update_agent(rt: Rt, me: Me, agent_id: str, body: AgentPatch) -> JSONResponse:
    """Saves the patched spec as a new draft version; what is live does not change until it is published."""
    reg = registry(rt)
    row = await reg.row(agent_id)
    spec = dict((await reg.version(agent_id, int(row["version"])))["spec"])
    patch = body.model_dump(exclude_none=True, exclude={"note", "guardrails"}, by_alias=True)
    if body.tool_ids is not None:
        _check_tools(rt, body.tool_ids)
    spec.update(patch)
    if body.guardrails is not None:
        spec["guardrails"] = body.guardrails.model_dump(by_alias=True)
    await reg.save(agent_id, spec, by=me.email, note=body.note or "")
    return ok(await _view(rt, agent_id))


@router.delete("/{agent_id}", status_code=204, response_model=None)
async def delete_agent(rt: Rt, agent_id: str) -> Response:
    await registry(rt).delete(agent_id)
    take_down(rt, agent_id)
    return Response(status_code=204)


@router.get("/{agent_id}/versions", response_model=Envelope[list[AgentVersion]])
async def list_versions(rt: Rt, agent_id: str) -> JSONResponse:
    reg = registry(rt)
    row = await reg.row(agent_id)
    requests = await reg.requests("agent", agent_id)
    pending = next((r for r in requests if r["status"] == "pending"), None)
    rejected = {int(r["version"]) for r in requests if r["status"] == "rejected"}
    out: list[dict[str, Any]] = []
    for v in await reg.versions(agent_id):
        n = int(v["version"])
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


@router.post("/{agent_id}/versions/{version}/restore", response_model=Envelope[Agent])
async def restore_version(rt: Rt, me: Me, agent_id: str, version: int) -> JSONResponse:
    """Copies a version into a new draft; nothing publishes."""
    reg = registry(rt)
    old = await reg.version(agent_id, version)
    await reg.save(agent_id, dict(old["spec"]), by=me.email, note=f"Restored from v{version}")
    return ok(await _view(rt, agent_id))


@router.post("/{agent_id}/publish-requests", response_model=Envelope[PublishReview], status_code=201)
async def request_publish(rt: Rt, me: Me, agent_id: str, body: PublishRequestInput) -> JSONResponse:
    """Opens an `agent_publish` review for the newest draft. Approved at once under the dev auto-approve setting,
    which publishes the version: its definition goes live and its `agent:<id>` graph compiles."""
    reg = registry(rt)
    row = await reg.row(agent_id)
    require_newest_draft(row, body.version)
    await require_known_alias(rt, (await reg.version(agent_id, body.version))["spec"].get("model") or "")
    v = await reg.version(agent_id, body.version)
    spec = v["spec"]
    approved = auto_approves(rt)
    review_body: dict[str, Any] = {
        "agentId": agent_id,
        "agentName": spec["name"],
        "version": body.version,
        "fromVersion": row["published_version"],
        "note": body.note,
        "requestedBy": me.email,
        "savedBy": v["saved_by"],
        "tier": "low",
        "tierReason": "No live workflow pins it",
        "approvalsNeeded": 1,
        "candidate": None,
        "published": None,
        "failing": 0,
        "blockers": [],
        "changes": v["changes"],
    }
    req = await reg.open_request(
        "agent", agent_id, body.version, note=body.note, by=me.email, body=review_body, approved=approved
    )
    if approved:
        await reg.publish(agent_id, body.version, by=req["decided_by"], review_id=req["id"])
        if not row["paused"]:
            go_live(rt, agent_id, body.version, spec)
    return ok(review_view(req, name=spec["name"], slug=row["slug"]), status=201)


@router.post("/{agent_id}/paused", response_model=Envelope[Agent])
async def set_paused(rt: Rt, agent_id: str, body: PausedInput) -> JSONResponse:
    """Pausing stops new chats and new agent-graph threads; resuming serves the published version again."""
    reg = registry(rt)
    row = await reg.row(agent_id)
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


@router.post("/{agent_id}/test", response_model=Envelope[AgentTestTurn])
async def test_agent(rt: Rt, agent_id: str, body: TestInput) -> JSONResponse:
    """One kernel turn on the newest version, draft or not, with no thread kept. A write tool stops at its gate, so
    the reply says where production would pause instead of acting."""
    if rt.ports is None:
        raise ServiceUnavailable(rt.model_error or "No model is configured.", code="model_unavailable")
    reg = registry(rt)
    row = await reg.row(agent_id)
    defn = definition_of(agent_id, int(row["version"]), (await reg.version(agent_id, int(row["version"])))["spec"])
    req = TurnRequest(
        turn_id=new_id("turn"),
        run_id=new_id("run"),
        settings=rt.catalog.settings_for(defn, rt.settings.model_alias),
        tools=rt.catalog.grants_for(defn),
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
    out: dict[str, Any] = {
        "reply": result.text,
        "toolCalls": [
            {"name": c.tool, "input": str(c.input), "output": "" if c.output is None else str(c.output)}
            for c in result.tool_calls
        ],
        "citations": [{"source": c.passage.title, "section": c.passage.section} for c in result.citations],
        "tookMs": round((time.perf_counter() - started) * 1000),
        "model": req.settings.model_alias,
    }
    if result.interrupt is not None:
        tool = rt.catalog.tool(result.interrupt.pending_call.tool)
        tpl = tool.approval if tool else None
        out["wouldPause"] = {
            "gate": tpl.gate if tpl else result.interrupt.needed,
            "reviewers": tpl.reviewers if tpl else "a reviewer",
        }
    return ok(out)
