"""`/v1/templates` (c-590): the agents, skills and workflows a team may install from its plugins, and the install that
makes the team's own copy.

tools-service is the one service that loads plugins; it answers the templates of the plugins on for the acting team,
with each body (`GET /v1/plugin-templates`). A copy is made through the checks its create route makes, called here
rather than copied, so a copy can never be something a person's create would refuse. Where a copy came from is a
`template_copies` row; the copy itself is an ordinary draft the team edits and publishes through its review.

The routes act in the caller's team and refuse a call that names none, since a copy saved with no team would be every
team's. `source` is `plugin:<plugin id>` now; a built-in pack is another source later, on the same routes."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_contracts.chat import WireModel
from ops_identity import ServiceCallError, ServiceUnreachable
from ops_service_kit.errors import ApiError, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import Envelope
from ops_service_kit.ids import new_id

from ...store.template_copies import TemplateCopies
from ...store.tenancy import current_team
from ..agent_registry import GUARDRAILS, registry
from ..auth import Principal, caller, require_builder
from ..deps import Runtime, runtime
from ..envelope import ok
from ..skills import check_content, skills

# The agent create route's own checks, called rather than copied, so a copy is refused exactly as a create is.
from . import agents as agent_routes
from .agents import require_known_alias
from .engine import DefinitionInput, create_definition, definitions
from .skills import SkillCreateInput

router = APIRouter(prefix="/v1/templates", tags=["templates"])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller)]  # noqa: UP040

Kind = Literal["agent", "skill", "workflow"]
KINDS: tuple[Kind, ...] = ("agent", "skill", "workflow")
# The area a kind's builder role is checked in, as its create route checks it.
AREAS: dict[str, str] = {"agent": "agents", "skill": "skills", "workflow": "workflows"}


class TemplatePlugin(WireModel):
    id: str
    title: str
    version: str


class TemplateRequires(WireModel):
    tools: list[str]
    bind: list[dict[str, str]]


class Installed(WireModel):
    # Live copies the team holds of this template, the newest version among them, and whether the source ships a
    # newer one. A copy never changes by itself; updating one is a later card.
    copies: int
    version: int | None
    newer_available: bool
    # The newest live copy was made from a body other than the template's current one (its digest differs).
    changed: bool = False


class TemplateView(WireModel):
    source: str
    plugin: TemplatePlugin
    kind: Kind
    id: str
    version: int
    title: str
    requires: TemplateRequires
    installed: Installed


class InstallInput(WireModel):
    # The version listed now when left out; another one is 404 template_version_not_found.
    version: int | None = Field(default=None, ge=1)
    # The copy's name; the template's when left out.
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # The team's own knowledge bases and model alias for the template's bindings; a binding left out is named in
    # `needs` and the copy is made without it.
    knowledge_bases: list[str] = Field(default_factory=list[str], max_length=20)
    model_alias: str | None = Field(default=None, min_length=1, max_length=200)


class CopyRef(WireModel):
    id: str
    kind: Kind
    record_id: str
    source: str
    template_id: str
    version: int


class Installation(WireModel):
    copy_: CopyRef = Field(alias="copy")
    created: bool
    # A binding the install left for the person: `{"knowledgeBase": "<what it is>"}` or `{"modelAlias": "<what>"}`.
    needs: list[dict[str, str]]


class TemplateNotFound(ApiError):
    status = 404
    code = "template_not_found"


def _team(me: Principal) -> str:
    """The team the request acts in. A dev session acts across teams, so a copy it saved would be no team's (every
    team's, engine.py's definition save); templates are installed into one team, so such a call is refused."""
    team = current_team()
    if not team or (me.team_id and me.team_id != team):
        raise ValidationFailed("Templates are installed into one team; this call acts in none.", code="team_required")
    return team


async def _listed(rt: Runtime, team: str, kind: str | None) -> list[dict[str, Any]]:
    """The templates of the plugins on for the team, from tools-service, of this service's kinds. The token names the
    team: the gateway's client names none by itself, and tools-service lists templates per team."""
    tools = rt.tool_reviews
    if tools is None:
        raise ServiceUnavailable("Templates come from tools-service, and this service has no address for it.")
    try:
        params = {"kind": kind} if kind else None
        rows = cast(list[dict[str, Any]], await tools.tools.get("/v1/plugin-templates", params=params, team=team))
    except (ServiceCallError, ServiceUnreachable) as e:
        raise ServiceUnavailable("tools-service did not answer with the team's templates. Try again shortly.") from e
    return [t for t in rows if t.get("kind") in KINDS]


def _copy_view(row: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "kind", "record_id", "source", "template_id", "version")
    return CopyRef.model_validate({k: row[k] for k in keys}).model_dump(by_alias=True)


@router.get("", response_model=Envelope[list[TemplateView]])
async def list_templates(rt: Rt, me: Me, kind: Annotated[Kind | None, Query()] = None) -> JSONResponse:
    """The agents, skills and workflows the team's plugins bring, each with the copies the team holds of it."""
    team = _team(me)
    held = await TemplateCopies(rt.db).of_team()
    out: list[dict[str, Any]] = []
    for t in await _listed(rt, team, kind):
        mine = [c for c in held if c["source"] == t["source"] and c["template_id"] == t["id"]]
        newest = max((int(c["version"]) for c in mine), default=None)
        latest = max(mine, key=lambda c: (int(c["version"]), str(c["installed_at"])), default=None)
        installed = {
            "copies": len(mine),
            "version": newest,
            "newerAvailable": newest is not None and newest < t["version"],
            "changed": latest is not None and bool(t.get("digest")) and latest.get("digest") != t.get("digest"),
        }
        view = {k: t[k] for k in ("source", "plugin", "kind", "id", "version", "title", "requires")}
        out.append(TemplateView.model_validate(view | {"installed": installed}).model_dump(by_alias=True))
    return ok(out)


async def _record_exists(rt: Runtime, kind: str, record_id: str) -> bool:
    """Whether the copy's record still stands; a deleted one lets the template be installed again."""
    if kind == "workflow":
        return await definitions(rt).get(record_id, team=current_team()) is not None
    try:
        await (registry(rt).row(record_id) if kind == "agent" else skills(rt).row(record_id))
    except NotFound:
        return False
    return True


async def _make_agent(rt: Runtime, me: Principal, team: str, t: dict[str, Any], body: InstallInput) -> str:
    """The agent create route's spec, through its checks: the tools offered to the team (400 `unknown_tool`), the
    team's knowledge bases (422 `unknown_knowledge_base`) and a served model alias (422 `unknown_model_alias`)."""
    b = cast(dict[str, Any], t.get("body") or {})
    tools = await agent_routes._checked_tools(rt, list(t["requires"]["tools"]), [])  # pyright: ignore[reportPrivateUsage]
    await agent_routes._check_knowledge(rt, body.knowledge_bases, [])  # pyright: ignore[reportPrivateUsage]
    model = body.model_alias or str(b.get("model") or "")
    await require_known_alias(rt, model)
    name = body.name or str(b.get("name") or t["title"])
    role = str(b.get("role") or t["title"])
    spec: dict[str, Any] = {
        "name": name,
        "role": role,
        "model": model,
        "channels": list(b.get("channels") or ["chat"]),
        "instructions": str(b.get("instructions") or f"You are {name}. {role}"),
        "toolIds": tools,
        "collections": list(body.knowledge_bases),
        "suggestions": [],
        "guardrails": GUARDRAILS,
    }
    return await registry(rt).create(spec, by=me.email, team_id=team)


async def _make_skill(rt: Runtime, me: Principal, team: str, t: dict[str, Any], body: InstallInput) -> str:
    """The skill create route's content, through `check_content` (a tool the team is not offered is refused); a draft
    owned by the team, marked imported."""
    b = cast(dict[str, Any], t.get("body") or {})
    fields = SkillCreateInput.model_validate(
        {
            **{k: v for k, v in b.items() if k not in ("tool_ids", "toolIds", "owner_team", "ownerTeam", "origin")},
            "name": body.name or b.get("name") or t["title"],
            "owner_team": team,
            "tool_ids": list(t["requires"]["tools"]),
            "knowledge_bases": list(body.knowledge_bases),
            "origin": "imported",
        }
    )
    content = await check_content(rt, fields.model_dump(by_alias=True))
    return await skills(rt).create(content, owner_team=team, team_id=team, origin="imported", by=me.email)


async def _make_workflow(rt: Runtime, me: Principal, t: dict[str, Any], body: InstallInput) -> str:
    """The workflow definition create route itself, so the engine's checks, the AI steps setting and pinning all
    apply; the copy gets an id of its own, since a workflow id belongs to one team."""
    definition = dict(cast(dict[str, Any], t.get("body") or {}))
    base = str(definition.get("id") or t["id"]).replace("-", "_")
    definition["id"] = f"{base}_{new_id('x').split('_', 1)[1][:6]}"
    if body.name:
        definition["name"] = body.name
    answer = await create_definition(rt, me, DefinitionInput(definition=definition))
    return str(json.loads(bytes(answer.body))["data"]["workflowId"])


def _needs(t: dict[str, Any], body: InstallInput) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for bind in cast(list[dict[str, str]], t["requires"].get("bind") or []):
        if "knowledge_base" in bind and not body.knowledge_bases:
            out.append({"knowledgeBase": bind["knowledge_base"]})
        if "model_alias" in bind and not body.model_alias:
            out.append({"modelAlias": bind["model_alias"]})
    return out


@router.post(
    "/{source}/{template_id}/install",
    response_model=Envelope[Installation],
    status_code=201,
    responses={200: {"model": Envelope[Installation], "description": "The team already holds a copy of this version"}},
)
async def install_template(rt: Rt, me: Me, source: str, template_id: str, body: InstallInput) -> JSONResponse:
    """Makes the team's own copy of the template: 201 with it, or 200 with the copy the team already holds of this
    version. 404 `template_not_found` when the team's plugins bring no such template (its plugin off for the team),
    `template_version_not_found` for a version they do not ship."""
    team = _team(me)
    t = next((x for x in await _listed(rt, team, None) if x["source"] == source and x["id"] == template_id), None)
    if t is None:
        raise TemplateNotFound(f"No template {template_id} from {source} for this team; its plugin may be off for it.")
    if body.version is not None and body.version != t["version"]:
        raise TemplateNotFound(
            f"{source} ships {template_id} version {t['version']}, not {body.version}.",
            code="template_version_not_found",
        )
    kind = cast(Kind, t["kind"])
    require_builder(me, area=AREAS[kind], team_id=team, action="create", what=f"a {kind}")
    copies = TemplateCopies(rt.db)
    held = await copies.live(source, template_id, int(t["version"]))
    if held is not None:
        if await _record_exists(rt, kind, str(held["record_id"])):
            return ok({"copy": _copy_view(held), "created": False, "needs": []})
        await copies.removed(str(held["id"]))
    if kind == "agent":
        record_id = await _make_agent(rt, me, team, t, body)
    elif kind == "skill":
        record_id = await _make_skill(rt, me, team, t, body)
    else:
        record_id = await _make_workflow(rt, me, t, body)
    row, made = await copies.add(
        team_id=team,
        kind=kind,
        record_id=record_id,
        source=source,
        template_id=template_id,
        version=int(t["version"]),
        by=me.email,
        digest=cast(str | None, t.get("digest")),
    )
    if not made:
        # Another install of this version won the race: its copy stands, and the agent made here goes (a skill or
        # workflow draft made here stays as an unused draft of the team's).
        if kind == "agent":
            await registry(rt).delete(record_id)
        return ok({"copy": _copy_view(row), "created": False, "needs": []})
    return ok({"copy": _copy_view(row), "created": True, "needs": _needs(t, body)}, status=201)
