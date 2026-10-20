"""/v1/widgets: widget templates an agent version pins and fills in chat (c-082,
`.codeloop/wiki/concepts/chat-widgets.md`).

The seeded library (seed/widgets.json) is listed as published, platform-wide templates. A builder creates a widget in
their team, saves drafts, and requests its publish, decided in Reviews by someone other than whoever asked or saved
it (approved at once under the dev auto-approve setting). A retired widget takes no new pins. An agent pins one by
`{widgetId, version}` on PATCH /v1/agents/{id}, which snapshots it.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ops_agent_kernel.layout import required_tools
from ops_contracts.chat import WireModel
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Envelope, OptionsPage, options_page, options_window, page_window, paged

from ..agent_registry import registry as agent_registry
from ..auth import Principal, principal, require_builder, teams_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..publish_policy import decide
from ..rights import rights
from ..schemas import WidgetTemplateList, WidgetTemplateOut
from ..team_names import team_name
from ..widgets import check_content, listed, publish, seeded_widgets, view, widget_id_of, widgets

router = APIRouter(dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class WidgetInput(WireModel):
    name: str
    use_when: str
    tree: dict[str, Any]
    data_schema: dict[str, Any]
    sample: dict[str, Any] | None = None


class ReviewInput(WireModel):
    note: str = ""


class RetireInput(WireModel):
    reason: str


async def _mine(rt: Runtime, me: Principal, widget_id: str, what: str) -> dict[str, Any]:
    """The registry row when the caller may change it; another team's widget answers 404, as if it did not exist, and a
    member of the owning team outside the builder and admin roles gets 403."""
    row = await widgets(rt).find(widget_id)
    teams = teams_of(me)
    if row is None or (teams is not None and row["team_id"] not in teams):
        if rt.catalog.widget(widget_id) is not None:
            raise Conflict(
                f"{widget_id} is a platform widget from the seeded library; it cannot be edited here.",
                code="seeded_widget",
            )
        raise NotFound(f"Widget {widget_id}")
    require_builder(me, area="widgets", team_id=row["team_id"], action=what, what="this widget")
    return row


@router.get("/v1/widgets", response_model=Envelope[list[WidgetTemplateOut] | WidgetTemplateList])
async def list_widgets(
    rt: Rt,
    me: Me,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: str = "",
) -> JSONResponse:
    """The seeded library, then the caller's teams' widgets, newest version each, by name; the agent page's picker
    reads it whole. With `page`, one page of those whose name matches `search`: the seeded library's few matches come
    first, then the registry's, whose page and count are queried, not sliced."""
    teams = teams_of(me)
    if page is None:
        return ok(await listed(rt, teams))
    q = search.strip().lower()
    seeded = [w for w in await seeded_widgets(rt) if q in str(w["name"]).lower()]
    reg = widgets(rt)
    total = len(seeded) + await reg.count(teams, search)
    page, offset = page_window(total, page, page_size)
    shown = seeded[offset : offset + page_size]
    rows = await reg.page(teams, search, max(0, offset - len(seeded)), page_size - len(shown))
    return ok(paged(shown + [await view(rt, r["id"]) for r in rows], total, page, page_size))


@router.get("/v1/widgets/options", response_model=Envelope[OptionsPage])
async def widget_options(  # noqa: PLR0917 - FastAPI reads each query parameter from the signature
    rt: Rt,
    me: Me,
    search: str = "",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ids: Annotated[list[str] | None, Query()] = None,
    granted: Annotated[list[str] | None, Query()] = None,
) -> JSONResponse:
    """The agent page's widget picker (c-136): the seeded library's matches first, then the caller's teams' published,
    unretired widgets, searched and limited in the query. A widget whose buttons need a tool outside `granted` (the
    draft's tools) is offered disabled with the reason, as a pin of it is refused."""
    held = set(granted or [])
    teams = teams_of(me)
    q = search.strip().lower()

    def option(w: dict[str, Any]) -> dict[str, Any]:
        missing = [t for t in w["requiresTools"] if t not in held]
        reason = f"Needs {', '.join(missing)}; grant it first." if missing else None
        return {
            "id": w["widgetId"],
            "label": w["name"],
            "hint": f"v{w['version']} · {w['useWhen']}",
            "disabled": reason,
        }

    every = await seeded_widgets(rt)
    seeded = (
        [w for w in every if w["widgetId"] in ids]
        if ids is not None
        else [w for w in every if q in str(w["name"]).lower()]
    )
    offset, window = options_window(None if ids else cursor, limit)
    shown = seeded[offset : offset + window]
    reg = widgets(rt)
    rows = await reg.pinnable(teams, search, max(0, offset - len(seeded)), window - len(shown), ids)
    views: list[dict[str, Any]] = []
    for r in rows:
        n = int(r["published_version"] or r["version"])
        found = await reg.version(r["id"], n)
        content = cast(dict[str, Any], found["content"]) if found else {}
        tree = cast(dict[str, Any], content.get("tree") or {})
        views.append(
            {
                "widgetId": r["id"],
                "name": r["name"],
                "version": n,
                "useWhen": content.get("useWhen", ""),
                "requiresTools": required_tools(tree),
            }
        )
    return ok(options_page([option(w) for w in shown + views], offset, limit))


@router.get("/v1/widgets/{widget_id}", response_model=Envelope[WidgetTemplateOut])
async def get_widget(rt: Rt, me: Me, widget_id: str) -> JSONResponse:
    found = next((w for w in await listed(rt, teams_of(me)) if w["widgetId"] == widget_id), None)
    if found is None:
        raise NotFound(f"Widget {widget_id}")
    words = {"edit": "save", "delete": "retire"}
    rights_of = await rights(lambda action: _mine(rt, me, widget_id, action), words)
    return ok({**found, **await team_name(rt, found.get("teamId")), **rights_of})


@router.post("/v1/widgets", response_model=Envelope[WidgetTemplateOut], status_code=201)
async def create_widget(rt: Rt, me: Me, body: WidgetInput) -> JSONResponse:
    require_builder(me, area="widgets", team_id=me.team_id, action="create", what="a widget")
    content = check_content(body.model_dump(by_alias=True))
    wid = widget_id_of(content["name"])
    if rt.catalog.widget(wid) is not None:
        raise Conflict(f"{wid} is taken by a platform widget; rename yours.", code="widget_taken")
    await widgets(rt).create(wid, content, team_id=me.team_id or "", by=me.email)
    return ok(await view(rt, wid), 201)


@router.patch("/v1/widgets/{widget_id}", response_model=Envelope[WidgetTemplateOut])
async def save_widget(rt: Rt, me: Me, widget_id: str, body: WidgetInput) -> JSONResponse:
    """Edits the newest draft, or opens the next version on top of the published one. 409 while retired or in
    review."""
    row = await _mine(rt, me, widget_id, "save")
    if row["retired_reason"]:
        raise Conflict("The widget is retired; it takes no new versions.", code="widget_retired")
    if any(r["status"] == "pending" for r in await agent_registry(rt).requests("widget", widget_id)):
        raise Conflict("The newest version is in review; decide the review first.", code="review_open")
    await widgets(rt).save_draft(widget_id, check_content(body.model_dump(by_alias=True)), by=me.email)
    return ok(await view(rt, widget_id))


@router.post("/v1/widgets/{widget_id}/publish-requests", response_model=Envelope[WidgetTemplateOut], status_code=201)
async def request_widget_publish(rt: Rt, me: Me, widget_id: str, body: ReviewInput) -> JSONResponse:
    """Opens a publish request for the newest draft; 409 when it is already published, in review or retired."""
    row = await _mine(rt, me, widget_id, "publish")
    reg = widgets(rt)
    n = int(row["version"])
    v = await reg.version(widget_id, n)
    assert v is not None
    if row["retired_reason"]:
        raise Conflict("The widget is retired.", code="widget_retired")
    if v["published_at"] is not None:
        raise Conflict(f"v{n} is already published; save a change to make a new version.", code="already_published")
    live = await reg.version(widget_id, int(row["published_version"])) if row["published_version"] else None
    decision = await decide(
        rt, area="widgets", team_id=row["team_id"], old=live["content"] if live else None, new=v["content"]
    )
    approved = not decision.review_required
    req = await agent_registry(rt).open_request(
        "widget",
        widget_id,
        n,
        note=body.note,
        by=me.email,
        body={
            "widgetId": widget_id,
            "widgetName": v["content"]["name"],
            "savedBy": v["saved_by"],
            **decision.record(),
            "changes": v["changes"],
        },
        approved=approved,
    )
    if approved:
        await publish(rt, req, "auto-approve (dev)")
    return ok(await view(rt, widget_id), 201)


@router.post("/v1/widgets/{widget_id}/retire", response_model=Envelope[WidgetTemplateOut])
async def retire_widget(rt: Rt, me: Me, widget_id: str, body: RetireInput) -> JSONResponse:
    """Terminal: new pins are refused, and agents that pin it keep the version they pinned."""
    if not body.reason.strip():
        raise ValidationFailed("Say why the widget is retired.", code="reason_required")
    await _mine(rt, me, widget_id, "retire")
    await widgets(rt).retire(widget_id, body.reason.strip(), by=me.email)
    return ok(await view(rt, widget_id))
