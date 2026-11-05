"""`/v1/templates`: the agents, skills and workflows a team may install from its plugins; and `/v1/resources`, Add to
team: the preview of what a set of resources brings, the copy that makes the team's own record, and an update taken
from a newer template.

tools-service is the one service that loads plugins; it answers the templates of the plugins on for the acting team,
with each body (`GET /v1/plugin-templates`). A copy is made through the checks its create route makes, called here
rather than copied, so a copy can never be something a person's create would refuse. Where a copy came from is a
`template_copies` row; the copy itself is an ordinary draft the team edits and publishes through its review.

A template names the other resources of its plugin it cannot run without (`requires.resources`, declared in the
manifest): a workflow is copied only once the team holds the agents its steps run, and its steps are pointed at the
team's copies. Document types are documents-service's; a workflow's document type steps are pointed at the copies
that service holds.

The routes act in the caller's team and refuse a call that names none, since a copy saved with no team would be every
team's. `source` is `plugin:<plugin id>` now; a built-in pack is another source later, on the same routes."""

from __future__ import annotations

import copy as deep
import json
from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_contracts.chat import WireModel
from ops_documents_client import DocumentsClient, DocumentsRefused
from ops_identity import ServiceCallError, ServiceUnreachable
from ops_service_kit.errors import (
    ApiError,
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    Unprocessable,
    ValidationFailed,
)
from ops_service_kit.http import Envelope
from ops_service_kit.ids import new_id

from ...store.template_copies import TemplateCopies
from ...store.tenancy import current_team
from ..agent_registry import GUARDRAILS, registry
from ..auth import Principal, caller, require_builder
from ..child_runs import team_workflows
from ..deps import Runtime, runtime
from ..envelope import ok
from ..skills import check_content, skills

# The agent create route's own checks, called rather than copied, so a copy is refused exactly as a create is.
from . import agents as agent_routes
from .agents import require_known_alias
from .engine import DefinitionInput, create_definition, definitions
from .skills import SkillCreateInput

router = APIRouter(prefix="/v1/templates", tags=["templates"])
# Add to team in the screen's words: a resource is an agent, skill or workflow an app brings, copied into the
# team. documents-service answers the same copy route for document types.
resources = APIRouter(prefix="/v1/resources", tags=["resources"])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller)]  # noqa: UP040

Kind = Literal["agent", "skill", "workflow"]
KINDS: tuple[Kind, ...] = ("agent", "skill", "workflow")
# Every kind an app brings, for a preview that spans services.
AnyKind = Literal["agent", "skill", "workflow", "document_type", "knowledge_source"]
# The area a kind's create is checked in, as its create route checks it.
AREAS: dict[str, str] = {"agent": "agents", "skill": "skills", "workflow": "workflows"}
# What a kind is called in a sentence a person reads.
NOUNS: dict[str, tuple[str, str]] = {
    "agent": ("an agent", "agents"),
    "skill": ("a skill", "skills"),
    "workflow": ("a workflow", "workflows"),
    "document_type": ("a document type", "document types"),
    "knowledge_source": ("a knowledge source", "knowledge sources"),
}
# The service that makes each kind's copy; a preview names it so the caller sends each add to the right one.
SERVICES: dict[str, str] = {
    "agent": "agents",
    "skill": "agents",
    "workflow": "agents",
    "document_type": "documents",
    "knowledge_source": "kb",
}
# A preview's add order: what nothing depends on first, so every copy finds the copies it needs.
ORDER: dict[str, int] = {"document_type": 0, "skill": 0, "knowledge_source": 0, "agent": 1, "workflow": 2}
State = Literal["available", "added", "update_available", "removed_upstream"]
MAX_PLAN = 50


class TemplatePlugin(WireModel):
    id: str
    title: str
    version: str


class TemplateRequires(WireModel):
    tools: list[str]
    bind: list[dict[str, str]]
    # The plugin's other resources a copy cannot run without, each `<source>:<template id>`.
    resources: list[str] = Field(default_factory=list[str])


class Installed(WireModel):
    # Live copies the team holds of this template, the newest version among them, and whether the source ships a
    # newer one. A copy never changes by itself.
    copies: int
    version: int | None
    newer_available: bool
    # The newest live copy was made from a body other than the template's current one (its digest differs).
    changed: bool = False


class CopyRef(WireModel):
    id: str
    kind: Kind
    record_id: str
    source: str
    template_id: str
    version: int


class AddCell(WireModel):
    # The roles grid cell a person needs to add this resource, so another service listing it says the same.
    area: str
    action: str


class TemplateView(WireModel):
    source: str
    plugin: TemplatePlugin
    kind: Kind
    id: str
    version: int
    title: str
    requires: TemplateRequires
    installed: Installed
    # available: no copy yet; added: a copy of what the app ships now; update_available: the app ships a newer or
    # changed template than the copy was made from; removed_upstream: the team holds a copy the app no longer ships.
    state: State
    # Whether the caller's roles let them add it, so a screen offers Add only then.
    can_add: bool
    add_cell: AddCell
    # The team's newest live copy, which Open, Remove and an update act on.
    copy_: CopyRef | None = Field(default=None, alias="copy")


class InstallInput(WireModel):
    # The version listed now when left out; another one is 404 template_version_not_found.
    version: int | None = Field(default=None, ge=1)
    # The copy's name; the template's when left out. A name the team already uses for the kind is 409 name_taken.
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # The team's own knowledge bases and model alias for the template's bindings; a binding left out is named in
    # `needs` and the copy is made without it.
    knowledge_bases: list[str] = Field(default_factory=list[str], max_length=20)
    model_alias: str | None = Field(default=None, min_length=1, max_length=200)
    # Copies of other services the workflow's steps should name, by resource: the document types documents-service
    # made earlier in the same add. Left out, documents-service is asked for the team's copy.
    copies: dict[str, str] = Field(default_factory=dict[str, str], max_length=50)


class Installation(WireModel):
    copy_: CopyRef = Field(alias="copy")
    created: bool
    # A binding the install left for the person: `{"knowledgeBase": "<what it is>"}` or `{"modelAlias": "<what>"}`.
    needs: list[dict[str, str]]


class PlanInput(WireModel):
    # The resources the person ticked, each `<source>:<template id>`.
    resources: list[str] = Field(min_length=1, max_length=MAX_PLAN)


class PlanRefusal(WireModel):
    code: str
    message: str
    # For name_taken: a name the copy could take instead.
    suggestion: str | None = None


class PlanItem(WireModel):
    resource: str
    kind: AnyKind
    title: str
    # Which service makes the copy: agents, documents or kb.
    service: str
    # The ticked resources that bring this one with them; empty for one the person ticked.
    brought_by: list[str]
    # The team's copy, when it holds one: used as it is, not copied again.
    held: CopyRef | None = None
    held_record_id: str | None = None
    tools: list[str]
    # Bindings the person fills before the add: `{"knowledgeBase": "<what>"}`, `{"modelAlias": "<what>"}`.
    bindings: list[dict[str, str]]
    refusal: PlanRefusal | None = None


class Plan(WireModel):
    # Every resource to make or use, in the order the adds run.
    items: list[PlanItem]
    # Whether every item that is not held can be made by the caller now.
    ready: bool


class UpdateInput(WireModel):
    # The person saw that the update does not carry the team's edits, and takes it anyway.
    confirm: bool = False


class UpdateReview(WireModel):
    copy_: CopyRef = Field(alias="copy")
    # The version the copy was made from, and the one the app ships now.
    from_version: int
    to_version: int
    # The fields the new template changes against the copy as it was made.
    changes: list[str]
    # The fields the team changed in its copy since; the new draft does not carry them.
    edits: list[str]
    # True once the update made the copy's new draft version.
    taken: bool = False


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


async def _offered(rt: Runtime, team: str) -> list[dict[str, Any]]:
    """Every resource the plugins on for the team bring, of every kind, from tools-service. The token names the team:
    the gateway's client names none by itself, and tools-service lists templates per team."""
    tools = rt.tool_reviews
    if tools is None:
        raise ServiceUnavailable("Templates come from tools-service, and this service has no address for it.")
    try:
        return cast(list[dict[str, Any]], await tools.tools.get("/v1/plugin-templates", team=team))
    except (ServiceCallError, ServiceUnreachable) as e:
        raise ServiceUnavailable("tools-service did not answer with the team's templates. Try again shortly.") from e


def _copy_view(row: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "kind", "record_id", "source", "template_id", "version")
    return CopyRef.model_validate({k: row[k] for k in keys}).model_dump(by_alias=True)


def _may_add(me: Principal, kind: str, team: str) -> bool:
    try:
        require_builder(me, area=AREAS[kind], team_id=team, action="create", what=NOUNS[kind][0])
    except Forbidden:
        return False
    return True


def _require_add(me: Principal, kind: str, team: str) -> None:
    """The kind's create check; its refusal names who may add it, never a grid cell or a team id."""
    require_builder(me, area=AREAS[kind], team_id=team, action="create", what=NOUNS[kind][0])


def _state(installed: dict[str, Any], offered: bool) -> State:
    if not offered:
        return "removed_upstream"
    if installed["copies"] == 0:
        return "available"
    return "update_available" if installed["newerAvailable"] or installed["changed"] else "added"


async def _record_name(rt: Runtime, kind: str, record_id: str) -> str | None:
    """The copy's own name now, or None once its record is gone."""
    try:
        if kind == "agent":
            row = await registry(rt).row(record_id)
            return str((await registry(rt).version(record_id, int(row["version"])))["spec"].get("name") or "")
        if kind == "skill":
            row = await skills(rt).row(record_id)
            found = await skills(rt).version(record_id, int(row["version"]))
            content = cast(dict[str, Any], (found or {}).get("content") or {})
            return str(content.get("name") or "")
    except NotFound:
        return None
    found = await definitions(rt).get(record_id, team=current_team())
    return str(found["name"]) if found else None


async def _record_digest(rt: Runtime, kind: str, record_id: str) -> str | None:
    """The digest of the record's newest version, which an edit moves."""
    try:
        if kind == "agent":
            row = await registry(rt).row(record_id)
            return str((await registry(rt).version(record_id, int(row["version"])))["digest"])
        if kind == "skill":
            row = await skills(rt).row(record_id)
            found = await skills(rt).version(record_id, int(row["version"]))
            return str(found["digest"]) if found else None
    except NotFound:
        return None
    found = await definitions(rt).get(record_id, team=current_team())
    return str(found["digest"]) if found else None


@router.get("", response_model=Envelope[list[TemplateView]])
async def list_templates(
    rt: Rt,
    me: Me,
    kind: Annotated[Kind | None, Query()] = None,
    source: Annotated[str | None, Query(max_length=200)] = None,
) -> JSONResponse:
    """The agents, skills and workflows the team's plugins bring, each with its state for the team, the copies the team
    holds of it and whether the caller may add it; `source` keeps one plugin's. A copy whose template the app no longer
    ships, while the app is still on, is listed too, as `removed_upstream`; a copy of an app turned off for the team
    reads `added`, with nothing to add."""
    team = _team(me)
    held = await TemplateCopies(rt.db).of_team()
    offered = await _offered(rt, team)
    on_sources = {str(t["source"]) for t in offered}
    out: list[dict[str, Any]] = []
    shipped: set[tuple[str, str]] = set()
    for t in offered:
        if t.get("kind") not in KINDS or kind not in (None, t["kind"]):
            continue
        if source is not None and t["source"] != source:
            continue
        shipped.add((str(t["source"]), str(t["id"])))
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
        out.append(
            TemplateView.model_validate(
                view
                | {
                    "installed": installed,
                    "state": _state(installed, True),
                    "canAdd": _may_add(me, t["kind"], team),
                    "addCell": {"area": AREAS[t["kind"]], "action": "create"},
                    "copy": _copy_view(latest) if latest else None,
                }
            ).model_dump(by_alias=True)
        )
    plugins = {str(t["source"]): t["plugin"] for t in offered}
    for c in held:
        at = (str(c["source"]), str(c["template_id"]))
        if at in shipped or kind not in (None, c["kind"]):
            continue
        if source is not None and c["source"] != source:
            continue
        name = await _record_name(rt, str(c["kind"]), str(c["record_id"]))
        if name is None:
            continue
        shipped.add(at)
        installed = {"copies": 1, "version": int(c["version"]), "newerAvailable": False, "changed": False}
        out.append(
            TemplateView.model_validate(
                {
                    "source": c["source"],
                    "plugin": plugins.get(str(c["source"])) or _plugin_of(str(c["source"])),
                    "kind": c["kind"],
                    "id": c["template_id"],
                    "version": int(c["version"]),
                    "title": name,
                    "requires": {"tools": [], "bind": []},
                    "installed": installed,
                    "state": "removed_upstream" if c["source"] in on_sources else "added",
                    "canAdd": False,
                    "addCell": {"area": AREAS[str(c["kind"])], "action": "create"},
                    "copy": _copy_view(c),
                }
            ).model_dump(by_alias=True)
        )
    return ok(out)


def _plugin_of(source: str) -> dict[str, str]:
    """A source tools-service does not list for the team (its app is off): named by its id alone."""
    plugin = source.removeprefix("plugin:")
    return {"id": plugin, "title": plugin, "version": ""}


async def _record_exists(rt: Runtime, kind: str, record_id: str) -> bool:
    """Whether the copy's record still stands; a deleted one lets the template be installed again."""
    return await _record_name(rt, kind, record_id) is not None


async def _names_in_use(rt: Runtime, kind: str) -> set[str]:
    """The names the team's records of this kind carry now, folded for comparison."""
    if kind == "agent":
        rows = await registry(rt).rows()
        named = await registry(rt).named_versions({(str(r["id"]), int(r["version"])) for r in rows})
        return {name.casefold() for name, _ in named.values()}
    if kind == "workflow":
        return {str(d["name"]).casefold() for d in await team_workflows(rt) if not d.get("archived_at")}
    # A skill's name is unique by its slug, which the skill store refuses as name_taken itself.
    return set()


def _name_taken(kind: str, name: str, app: str) -> Conflict:
    return Conflict(
        f"Your team already has {NOUNS[kind][0]} named {name}. Add this one under another name, such as {name}, {app}.",
        code="name_taken",
        details={"suggestion": f"{name}, {app}"},
    )


def _spec_of(t: dict[str, Any], name: str, model: str, tools: list[str], bases: list[str]) -> dict[str, Any]:
    b = cast(dict[str, Any], t.get("body") or {})
    role = str(b.get("role") or t["title"])
    return {
        "name": name,
        "role": role,
        "model": model,
        "channels": list(b.get("channels") or ["chat"]),
        "instructions": str(b.get("instructions") or f"You are {name}. {role}"),
        "toolIds": tools,
        "collections": list(bases),
        "suggestions": [],
        "guardrails": GUARDRAILS,
    }


async def _make_agent(rt: Runtime, me: Principal, team: str, t: dict[str, Any], body: InstallInput) -> str:
    """The agent create route's spec, through its checks: the tools offered to the team (400 `unknown_tool`), the
    team's knowledge bases (422 `unknown_knowledge_base`) and a served model alias (422 `unknown_model_alias`)."""
    b = cast(dict[str, Any], t.get("body") or {})
    tools = await agent_routes._checked_tools(rt, list(t["requires"]["tools"]), [])  # pyright: ignore[reportPrivateUsage]
    await agent_routes._check_knowledge(rt, body.knowledge_bases, [])  # pyright: ignore[reportPrivateUsage]
    model = body.model_alias or str(b.get("model") or "")
    await require_known_alias(rt, model)
    name = body.name or str(b.get("name") or t["title"])
    return await registry(rt).create(_spec_of(t, name, model, tools, body.knowledge_bases), by=me.email, team_id=team)


async def _skill_content(rt: Runtime, team: str, t: dict[str, Any], name: str, bases: list[str]) -> dict[str, Any]:
    """The skill create route's content, through `check_content` (a tool the team is not offered is refused)."""
    b = cast(dict[str, Any], t.get("body") or {})
    fields = SkillCreateInput.model_validate(
        {
            **{k: v for k, v in b.items() if k not in ("tool_ids", "toolIds", "owner_team", "ownerTeam", "origin")},
            "name": name,
            "owner_team": team,
            "tool_ids": list(t["requires"]["tools"]),
            "knowledge_bases": list(bases),
            "origin": "imported",
        }
    )
    return await check_content(rt, fields.model_dump(by_alias=True))


async def _make_skill(rt: Runtime, me: Principal, team: str, t: dict[str, Any], body: InstallInput) -> str:
    """A draft skill owned by the team, marked imported."""
    b = cast(dict[str, Any], t.get("body") or {})
    content = await _skill_content(rt, team, t, body.name or str(b.get("name") or t["title"]), body.knowledge_bases)
    return await skills(rt).create(content, owner_team=team, team_id=team, origin="imported", by=me.email)


def _pointed(definition: dict[str, Any], records: dict[str, str]) -> dict[str, Any]:
    """The definition with each agent step and document type step that names a template id of `records` pointed at
    the team's copy of it instead."""
    out = deep.deepcopy(definition)
    for node in cast(list[dict[str, Any]], out.get("nodes") or []):
        params = cast(dict[str, Any], node.get("parameters") or {})
        if node.get("type") == "ops.ai.agent" and str(params.get("agent") or "") in records:
            params["agent"] = records[str(params["agent"])]
        doc_type = params.get("documentType")
        if isinstance(doc_type, dict):
            ref = cast(dict[str, Any], doc_type)
            if str(ref.get("id") or "") in records:
                ref["id"] = records[str(ref["id"])]
                ref.pop("version", None)
    return out


async def _make_workflow(
    rt: Runtime, me: Principal, t: dict[str, Any], body: InstallInput, records: dict[str, str]
) -> str:
    """The workflow definition create route itself, so the engine's checks, the AI steps setting and pinning all
    apply; the copy gets an id of its own, since a workflow id belongs to one team, and its steps run the team's
    copies of the resources it needs."""
    definition = _pointed(dict(cast(dict[str, Any], t.get("body") or {})), records)
    base = str(definition.get("id") or t["id"]).replace("-", "_")
    definition["id"] = f"{base}_{new_id('x').split('_', 1)[1][:6]}"
    if body.name:
        definition["name"] = body.name
    answer = await create_definition(rt, me, DefinitionInput(definition=definition))
    return str(json.loads(bytes(answer.body))["data"]["workflowId"])


def _needs(t: dict[str, Any], bases: list[str], alias: str | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for bind in cast(list[dict[str, str]], t["requires"].get("bind") or []):
        if "knowledge_base" in bind and not bases:
            out.append({"knowledgeBase": bind["knowledge_base"]})
        if "model_alias" in bind and not alias:
            out.append({"modelAlias": bind["model_alias"]})
    return out


def resource_ref(resource: str) -> tuple[str, str]:
    """`<source>:<template id>` as the app's resource list names it; the source carries a colon of its own
    (`plugin:<id>`), so the template id is what follows the last one."""
    source, _, template_id = resource.rpartition(":")
    if not source or not template_id:
        raise TemplateNotFound(f"No resource {resource}; a resource is named <source>:<template id>.")
    return source, template_id


def _documents(rt: Runtime) -> DocumentsClient | None:
    if not rt.settings.documents_url:
        return None
    return DocumentsClient.from_settings(rt.settings, service="agents", scopes=["documents:view"])


async def _held_documents(rt: Runtime, me: Principal, team: str) -> dict[str, str]:
    """By resource, the record of the team's copy of each document type documents-service holds; empty when this
    service has no address for it."""
    documents = _documents(rt)
    if documents is None:
        return {}
    try:
        rows = await documents.template_copies(me.tenant_id, team)
    except (DocumentsRefused, ServiceUnreachable):
        return {}
    finally:
        await documents.aclose()
    return {
        f"{r['source']}:{r['id']}": str(r["copy"]["recordId"])
        for r in rows
        if r.get("copy") and r.get("state") != "available"
    }


async def _held_records(rt: Runtime, wanted: list[str]) -> dict[str, str]:
    """By resource, the record of the team's newest live copy of each of this service's kinds in `wanted`, at any
    version (a copy of an older version still runs)."""
    out: dict[str, str] = {}
    held = await TemplateCopies(rt.db).of_team()
    for resource in wanted:
        source, template_id = resource_ref(resource)
        mine = [c for c in held if c["source"] == source and c["template_id"] == template_id]
        for c in sorted(mine, key=lambda c: (int(c["version"]), str(c["installed_at"])), reverse=True):
            if await _record_exists(rt, str(c["kind"]), str(c["record_id"])):
                out[resource] = str(c["record_id"])
                break
    return out


async def _dependencies(
    rt: Runtime,
    me: Principal,
    team: str,
    t: dict[str, Any],
    *,
    offered: dict[str, dict[str, Any]],
    given: dict[str, str],
) -> dict[str, str]:
    """Template id to the team's record for each resource the template needs, or 422 `dependency_missing` naming every
    one the team does not hold yet; nothing is made then."""
    wanted = [str(r) for r in cast(list[Any], t["requires"].get("resources") or [])]
    if not wanted:
        return {}
    records = await _held_records(rt, [r for r in wanted if (offered.get(r) or {}).get("kind") in KINDS])
    if any((offered.get(r) or {}).get("kind") == "document_type" and r not in given for r in wanted):
        records |= await _held_documents(rt, me, team)
    records |= {r: v for r, v in given.items() if r in wanted}
    missing = [r for r in wanted if r not in records]
    if missing:
        titles = [str((offered.get(r) or {}).get("title") or resource_ref(r)[1]) for r in missing]
        names = " and ".join(titles)
        raise Unprocessable(
            f"{t['title']} needs {names}, which your team has not added. Add {names} first, or add them together.",
            code="dependency_missing",
            details={"missing": [{"resource": r, "title": n} for r, n in zip(missing, titles, strict=True)]},
        )
    return {resource_ref(r)[1]: records[r] for r in wanted}


def _template(offered: dict[str, dict[str, Any]], source: str, template_id: str) -> dict[str, Any]:
    t = offered.get(f"{source}:{template_id}")
    if t is None or t.get("kind") not in KINDS:
        raise TemplateNotFound(f"No template {template_id} from {source} for this team; its plugin may be off for it.")
    return t


@resources.post(
    "/{resource}/copies",
    response_model=Envelope[Installation],
    status_code=201,
    responses={200: {"model": Envelope[Installation], "description": "The team already holds a copy of this version"}},
)
async def copy_resource(rt: Rt, me: Me, resource: str, body: InstallInput) -> JSONResponse:
    """Add to team: makes the team's own copy of the resource, 201 with it, or 200 with the copy the team already holds
    of this version. 404 `template_not_found` when the team's apps bring no such resource (its app off for the team),
    `template_version_not_found` for a version they do not ship; 409 `name_taken` when the team already has a record
    of the kind by that name; 422 `dependency_missing` naming each resource it needs that the team has not added."""
    source, template_id = resource_ref(resource)
    team = _team(me)
    offered = {f"{x['source']}:{x['id']}": x for x in await _offered(rt, team)}
    t = _template(offered, source, template_id)
    if body.version is not None and body.version != t["version"]:
        raise TemplateNotFound(
            f"{source} ships {template_id} version {t['version']}, not {body.version}.",
            code="template_version_not_found",
        )
    kind = cast(Kind, t["kind"])
    _require_add(me, kind, team)
    copies = TemplateCopies(rt.db)
    held = await copies.live(source, template_id, int(t["version"]))
    if held is not None:
        if await _record_exists(rt, kind, str(held["record_id"])):
            return ok({"copy": _copy_view(held), "created": False, "needs": []})
        await copies.removed(str(held["id"]))
    records = await _dependencies(rt, me, team, t, offered=offered, given=body.copies)
    name = body.name or str(cast(dict[str, Any], t.get("body") or {}).get("name") or t["title"])
    if name.casefold() in await _names_in_use(rt, kind):
        raise _name_taken(kind, name, str(t["plugin"]["title"]))
    if kind == "agent":
        record_id = await _make_agent(rt, me, team, t, body)
    elif kind == "skill":
        try:
            record_id = await _make_skill(rt, me, team, t, body)
        except Conflict as e:
            if e.code != "name_taken":
                raise
            raise _name_taken(kind, name, str(t["plugin"]["title"])) from None
    else:
        record_id = await _make_workflow(rt, me, t, body, records)
    row, made = await copies.add(
        team_id=team,
        kind=kind,
        record_id=record_id,
        source=source,
        template_id=template_id,
        version=int(t["version"]),
        by=me.email,
        digest=cast(str | None, t.get("digest")),
        record_digest=await _record_digest(rt, kind, record_id),
    )
    if not made:
        # Another install of this version won the race: its copy stands, and the agent made here goes (a skill or
        # workflow draft made here stays as an unused draft of the team's).
        if kind == "agent":
            await registry(rt).delete(record_id)
        return ok({"copy": _copy_view(row), "created": False, "needs": []})
    needs = _needs(t, body.knowledge_bases, body.model_alias)
    return ok({"copy": _copy_view(row), "created": True, "needs": needs}, status=201)


@resources.post("/plan", response_model=Envelope[Plan])
async def plan_resources(rt: Rt, me: Me, body: PlanInput) -> JSONResponse:
    """The preview of Add selected: each ticked resource and each one it brings with it, the ones the team already
    holds (used as they are), the tools each uses, the bindings to fill, and anything the caller would be refused, in
    the order the adds run (document types and skills, then agents, then workflows). Nothing is made."""
    team = _team(me)
    offered = {f"{x['source']}:{x['id']}": x for x in await _offered(rt, team)}
    for r in body.resources:
        if r not in offered:
            source, template_id = resource_ref(r)
            raise TemplateNotFound(
                f"No template {template_id} from {source} for this team; its plugin may be off for it."
            )
    brought: dict[str, list[str]] = {r: [] for r in body.resources}
    queue = list(body.resources)
    held: dict[str, str] = {}
    held_rows: dict[str, dict[str, Any]] = {}
    copies = await TemplateCopies(rt.db).of_team()
    documents: dict[str, str] | None = None
    while queue:
        r = queue.pop(0)
        t = offered.get(r)
        if t is None:
            continue
        if t["kind"] in KINDS:
            found = await _held_records(rt, [r])
            if r in found:
                held[r] = found[r]
                held_rows[r] = next(c for c in copies if c["record_id"] == found[r])
        elif t["kind"] == "document_type":
            documents = documents if documents is not None else await _held_documents(rt, me, team)
            if r in documents:
                held[r] = documents[r]
        if r in held:
            continue
        for dep in cast(list[str], t["requires"].get("resources") or []):
            if dep not in brought:
                brought[dep] = []
                queue.append(dep)
            if r not in brought[dep] and dep not in body.resources:
                brought[dep].append(r)
    items: list[dict[str, Any]] = []
    names: dict[str, set[str]] = {}
    for r in sorted(brought, key=lambda r: (ORDER.get(str((offered.get(r) or {}).get("kind")), 3), r)):
        t = offered.get(r)
        if t is None:
            continue
        kind = str(t["kind"])
        refusal: dict[str, Any] | None = None
        if r not in held and kind in KINDS:
            try:
                _require_add(me, kind, team)
            except Forbidden as e:
                refusal = {"code": e.code, "message": e.message}
            else:
                names.setdefault(kind, await _names_in_use(rt, kind))
                if str(t["title"]).casefold() in names[kind]:
                    taken = _name_taken(kind, str(t["title"]), str(t["plugin"]["title"]))
                    refusal = {
                        "code": "name_taken",
                        "message": taken.message,
                        "suggestion": (taken.details or {})["suggestion"],
                    }
        items.append(
            {
                "resource": r,
                "kind": kind,
                "title": t["title"],
                "service": SERVICES[kind],
                "broughtBy": brought[r],
                "held": _copy_view(held_rows[r]) if r in held_rows else None,
                "heldRecordId": held.get(r),
                "tools": list(t["requires"].get("tools") or []),
                "bindings": [] if r in held else _needs(t, [], None),
                "refusal": refusal,
            }
        )
    ready = all(i["refusal"] is None for i in items)
    return ok(Plan.model_validate({"items": items, "ready": ready}).model_dump(by_alias=True))


def _fields_changed(before: dict[str, Any], after: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [k for k in keys if before.get(k) != after.get(k)]


AGENT_FIELDS = ("name", "role", "model", "channels", "instructions", "toolIds", "collections")
SKILL_FIELDS = ("name", "useWhen", "loading", "instructions", "tools", "knowledgeBases")


def _edits(
    baseline: dict[str, Any] | None, now: dict[str, Any], changes: list[str], keys: tuple[str, ...]
) -> list[str]:
    """What the team changed since the copy (or its last update) was made. A draft saved over in place keeps no
    earlier body, so then every field the update would replace counts, the team's edits among them."""
    if baseline is None:
        return changes or ["saved since it was added"]
    return _fields_changed(baseline, now, keys) or ["saved since it was added"]


async def _review(
    rt: Runtime, me: Principal, team: str, resource: str, record_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """The copy's row, its template now, the review of taking it, and the record's new body for an agent or skill.
    `changes` are the fields the new draft would change in the copy as it is now; `edits` are the team's changes since
    the copy was made, which the new draft does not carry."""
    source, template_id = resource_ref(resource)
    offered = {f"{x['source']}:{x['id']}": x for x in await _offered(rt, team)}
    t = _template(offered, source, template_id)
    kind = cast(Kind, t["kind"])
    row = await TemplateCopies(rt.db).of_record(kind, record_id)
    if row is None or row["source"] != source or row["template_id"] != template_id:
        raise NotFound(f"{record_id} is not the team's copy of {resource}.")
    require_builder(me, area=AREAS[kind], team_id=team, action="edit", what=f"the team's copy of {t['title']}")
    edited = row.get("record_digest") != await _record_digest(rt, kind, record_id)
    new: dict[str, Any] | None = None
    if kind == "agent":
        versions = await registry(rt).versions(record_id)
        now = cast(dict[str, Any], versions[0]["spec"])
        baseline = next((v["spec"] for v in versions if v["digest"] == row.get("record_digest")), None)
        tools = await agent_routes._checked_tools(rt, list(t["requires"]["tools"]), [])  # pyright: ignore[reportPrivateUsage]
        # The copy's bindings are the team's: its name, model and knowledge bases stay as they are.
        new = _spec_of(t, str(now["name"]), str(now.get("model") or ""), tools, list(now.get("collections") or []))
        changes = _fields_changed(now, new, AGENT_FIELDS)
        edits = _edits(baseline, now, changes, AGENT_FIELDS) if edited else []
    elif kind == "skill":
        versions = await skills(rt).versions(record_id)
        now = cast(dict[str, Any], versions[0]["content"])
        baseline = next((v["content"] for v in versions if v["digest"] == row.get("record_digest")), None)
        bases = list(now.get("knowledgeBases") or [])
        new = await _skill_content(rt, team, t, str(now.get("name") or t["title"]), bases)
        changes = _fields_changed(now, new, SKILL_FIELDS)
        edits = _edits(baseline, now, changes, SKILL_FIELDS) if edited else []
    else:
        changes = ["definition"] if row.get("digest") != t.get("digest") else []
        edits = ["definition"] if edited else []
    review = {
        "copy": _copy_view(row),
        "fromVersion": int(row["version"]),
        "toVersion": int(t["version"]),
        "changes": changes,
        "edits": edits,
    }
    return row, t, review, new


@resources.get("/{resource}/copies/{copy}/update", response_model=Envelope[UpdateReview])
async def review_update(rt: Rt, me: Me, resource: str, copy: str) -> JSONResponse:
    """Review update: what taking the app's current template would change in the team's copy (`copy` is the copy's
    record id), and the edits the team made to its copy since, which the new draft does not carry."""
    team = _team(me)
    _, _, review, _ = await _review(rt, me, team, resource, copy)
    return ok(UpdateReview.model_validate(review).model_dump(by_alias=True))


@resources.post("/{resource}/copies/{copy}/update", response_model=Envelope[UpdateReview])
async def take_update(rt: Rt, me: Me, resource: str, copy: str, body: UpdateInput) -> JSONResponse:
    """Take update: a new draft version of the copy made from the app's current template; the published version keeps
    running until the draft goes through its publish review, and earlier versions stay in the copy's history. A copy the
    team edited since it was added is refused with 409 `copy_edited`, listing the edits, until `confirm` says the
    person saw that the new draft does not carry them; nothing is merged."""
    team = _team(me)
    row, t, review, new = await _review(rt, me, team, resource, copy)
    if review["edits"] and not body.confirm:
        raise Conflict(
            f"Your team changed {t['title']} since adding it ({', '.join(review['edits'])}). The update makes a new "
            "draft from the app's template, without those changes. Confirm to take it.",
            code="copy_edited",
            details=review,
        )
    kind = str(t["kind"])
    note = f"Update from {t['plugin']['title']}, template version {t['version']}"
    if kind == "agent":
        assert new is not None
        await registry(rt).save(copy, new, by=me.email, note=note)
    elif kind == "skill":
        assert new is not None
        await skills(rt).save_draft(copy, new, by=me.email, note=note)
    else:
        held = await definitions(rt).get(copy, team=current_team())
        assert held is not None
        offered = {f"{x['source']}:{x['id']}": x for x in await _offered(rt, team)}
        records = await _dependencies(rt, me, team, t, offered=offered, given={})
        definition = _pointed(dict(cast(dict[str, Any], t.get("body") or {})), records)
        definition["id"], definition["name"] = copy, held["name"]
        await create_definition(rt, me, DefinitionInput(definition=definition))
    await TemplateCopies(rt.db).updated(
        str(row["id"]),
        version=int(t["version"]),
        digest=cast(str | None, t.get("digest")),
        record_digest=await _record_digest(rt, kind, copy),
    )
    refreshed = await TemplateCopies(rt.db).of_record(cast(Kind, kind), copy)
    taken = review | {"copy": _copy_view(refreshed or row), "taken": True}
    return ok(UpdateReview.model_validate(taken).model_dump(by_alias=True))


__all__ = ["resource_ref"]
