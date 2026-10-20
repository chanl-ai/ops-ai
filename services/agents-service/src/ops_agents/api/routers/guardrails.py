"""/v1/guardrails: guardrails as versioned attachments an agent pins (c-063, api/guardrails.py)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_contracts.chat import WireModel
from ops_service_kit.errors import Conflict
from ops_service_kit.http import Envelope, OptionsPage, options_page, options_window, page_window, paged
from ops_service_kit.logging import get_logger

from ..agent_registry import registry as agent_registry
from ..agent_registry import require_owner_or_admin
from ..auth import Principal, principal, require_builder
from ..deps import Runtime, runtime
from ..envelope import ok
from ..guardrails import check_config, decide, guardrails, pinned_by, publish, view
from ..publish_policy import decide as review_needed
from ..schemas import Guardrail, GuardrailList

log = get_logger("ops_agents.guardrails")
router = APIRouter(prefix="/v1/guardrails", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class GuardrailInput(WireModel):
    name: str
    kind: Literal["blocked_topics"] = "blocked_topics"
    topics: list[str] = Field(default_factory=list[str])
    message: str = ""
    # Topic to what it covers and what it does not, listed beside the topic for the classifier; optional per topic.
    scopes: dict[str, str] = Field(default_factory=dict[str, str])
    # Show the answer only once it has passed the after-answer check; off, it streams and is replaced on a hit.
    hold_until_checked: bool = False
    owner: str = "Operations"


class GuardrailPatch(WireModel):
    topics: list[str] | None = None
    message: str | None = None
    # Replaces the version's scopes whole; omitted keeps them (a scope whose topic is removed is dropped).
    scopes: dict[str, str] | None = None
    hold_until_checked: bool | None = None
    note: str = ""


class GuardrailPublishInput(WireModel):
    version: int
    note: str = ""


class GuardrailDecisionInput(WireModel):
    decision: Literal["approved", "rejected"]
    reason: str | None = None


class GuardrailStatusInput(WireModel):
    status: Literal["live", "deprecated"]


@router.get("", response_model=Envelope[list[Guardrail] | GuardrailList])
async def list_guardrails(
    rt: Rt,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: str = "",
) -> JSONResponse:
    """Every guardrail, which the agent page's pin picker reads whole; with `page`, one page of those whose name or
    owner matches `search`, as the Guardrails list reads it. The page and its count are queried, not sliced."""
    reg = guardrails(rt)
    if page is None:
        return ok([await view(rt, r["id"]) for r in await reg.rows()])
    total = await reg.count(search)
    page, offset = page_window(total, page, page_size)
    rows = [await view(rt, r["id"]) for r in await reg.page(search, offset, page_size)]
    return ok(paged(rows, total, page, page_size))


@router.get("/options", response_model=Envelope[OptionsPage])
async def guardrail_options(
    rt: Rt,
    search: str = "",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ids: Annotated[list[str] | None, Query()] = None,
) -> JSONResponse:
    """The agent page's guardrail picker (c-136): live guardrails with a published version, by name, searched and
    limited in the query; `ids` labels pins already held, whatever their state."""
    offset, window = options_window(None if ids else cursor, limit)
    rows = await guardrails(rt).pinnable(search, offset, window, ids)
    opts = [
        {"id": r["id"], "label": r["name"], "hint": f"v{r['published_version']} · {r['owner']}", "disabled": None}
        for r in rows
    ]
    return ok(options_page(opts, offset, limit))


@router.get("/{guardrail_id}", response_model=Envelope[Guardrail])
async def get_guardrail(rt: Rt, guardrail_id: str) -> JSONResponse:
    return ok(await view(rt, guardrail_id))


async def changeable(rt: Runtime, me: Principal, guardrail_id: str, action: str) -> dict[str, Any]:
    """The guardrail's row once the caller may change it (auth.require_builder: the roles grid, in the team that owns
    it or, for one no team owns, the team the request acts in)."""
    row = await guardrails(rt).row(guardrail_id)
    require_builder(me, area="guardrails", team_id=row["team_id"], action=action, what=f"guardrail {row['name']}")
    return row


@router.post("", response_model=Envelope[Guardrail], status_code=201)
async def create_guardrail(rt: Rt, me: Me, body: GuardrailInput) -> JSONResponse:
    require_builder(me, area="guardrails", team_id=me.team_id, action="create", what="a guardrail")
    config = check_config(
        body.kind,
        {
            "topics": body.topics,
            "message": body.message,
            "scopes": body.scopes,
            "holdUntilChecked": body.hold_until_checked,
        },
    )
    gid = await guardrails(rt).create(
        name=body.name.strip(), kind=body.kind, config=config, owner=body.owner, team_id=me.team_id or "", by=me.email
    )
    return ok(await view(rt, gid), 201)


@router.patch("/{guardrail_id}", response_model=Envelope[Guardrail])
async def update_guardrail(rt: Rt, me: Me, guardrail_id: str, body: GuardrailPatch) -> JSONResponse:
    """Saves the next version as a draft; agents keep the version they pin until a publish and a re-pin."""
    reg = guardrails(rt)
    row = await changeable(rt, me, guardrail_id, "edit")
    newest = await reg.version(guardrail_id, int(row["version"]))
    assert newest is not None
    merged: dict[str, Any] = {**newest["config"], **body.model_dump(by_alias=True, exclude_none=True, exclude={"note"})}
    await reg.save(guardrail_id, check_config(row["kind"], merged), by=me.email, note=body.note)
    return ok(await view(rt, guardrail_id))


@router.post("/{guardrail_id}/publish-requests", response_model=Envelope[Guardrail], status_code=201)
async def request_guardrail_publish(rt: Rt, me: Me, guardrail_id: str, body: GuardrailPublishInput) -> JSONResponse:
    """Opens a publish request for the newest draft; approved at once under the dev auto-approve setting."""
    reg = guardrails(rt)
    row = await changeable(rt, me, guardrail_id, "publish")
    if body.version != row["version"] or row["published_version"] == body.version:
        raise Conflict(f"v{body.version} is not the newest draft (v{row['version']}).", code="not_newest_draft")
    v = await reg.version(guardrail_id, body.version)
    assert v is not None
    live = await reg.version(guardrail_id, int(row["published_version"])) if row["published_version"] else None
    decision = await review_needed(
        rt, area="guardrails", team_id=row["team_id"], old=live["config"] if live else None, new=v["config"]
    )
    approved = not decision.review_required
    req = await agent_registry(rt).open_request(
        "guardrail",
        guardrail_id,
        body.version,
        note=body.note,
        by=me.email,
        body={
            "guardrailId": guardrail_id,
            "name": row["name"],
            "savedBy": v["saved_by"],
            "config": v["config"],
            **decision.record(),
        },
        approved=approved,
    )
    if approved:
        await publish(rt, req, "auto-approve (dev)")
    return ok(await view(rt, guardrail_id), 201)


@router.post("/{guardrail_id}/publish-requests/{request_id}/decision", response_model=Envelope[Guardrail])
async def decide_guardrail_publish(
    rt: Rt, me: Me, guardrail_id: str, request_id: str, body: GuardrailDecisionInput
) -> JSONResponse:
    await decide(rt, me, guardrail_id, request_id, body.decision, body.reason)
    return ok(await view(rt, guardrail_id))


@router.post("/{guardrail_id}/status", response_model=Envelope[Guardrail])
async def set_guardrail_status(rt: Rt, me: Me, guardrail_id: str, body: GuardrailStatusInput) -> JSONResponse:
    """Deprecated: no new pins; agents that pin it keep enforcing the version they pin."""
    await changeable(rt, me, guardrail_id, "change the status of")
    await guardrails(rt).set_status(guardrail_id, body.status)
    return ok(await view(rt, guardrail_id))


@router.delete("/{guardrail_id}", status_code=204, response_class=Response)
async def delete_guardrail(rt: Rt, me: Me, guardrail_id: str) -> Response:
    """Refused (403) unless the caller created the guardrail or is an admin of its team, and (409) while it is
    pinned. Who deleted it is logged; agents-service has no audit table yet."""
    row = await guardrails(rt).row(guardrail_id)
    first = await guardrails(rt).version(guardrail_id, 1)
    require_owner_or_admin(
        me, area="guardrails", team_id=row["team_id"], created_by=first["saved_by"] if first else "", what=row["name"]
    )
    if users := await pinned_by(rt, guardrail_id):
        raise Conflict(f"Pinned by {', '.join(users)}; unpin it first.", code="guardrail_pinned")
    await guardrails(rt).delete(guardrail_id)
    log.info("guardrail_deleted", guardrail=guardrail_id, name=row["name"], by=me.email)
    return Response(status_code=204)
