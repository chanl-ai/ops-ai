"""/v1/skills and /v1/agents/{id}/skills: skills as versioned attachments an agent pins (spec 11 SK-1 to SK-10 and
SK-23 to SK-25; api/skills.py). Tests, resources, generation, import and export (SK-11 to SK-22) are not served."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_contracts.chat import WireModel
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Envelope, OptionsPage, options_page, options_window
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger

from ...store.template_copies import TemplateCopies
from ..agent_registry import registry as agent_registry
from ..agent_registry import require_owner_or_admin
from ..auth import Principal, principal, require_builder
from ..deps import Runtime, runtime
from ..envelope import ok
from ..hitl_facade import page
from ..publish_policy import decide
from ..schemas import AgentSkills, SkillDetail, SkillList, SkillOptions
from ..skills import (
    LIMITS,
    _pinning,  # pyright: ignore[reportPrivateUsage]
    agent_skills,
    check_content,
    detail,
    missing_for,
    pin,
    pinned_by,
    publish,
    require_unpinned,
    row_view,
    skills,
)
from .agents import changeable as agent_changeable
from .tool_catalog import known_tools

log = get_logger("ops_agents.skills")
router = APIRouter(dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
VIEWS = ("all", "published", "always", "drafts", "in_review", "deprecated", "unused")


class SkillCreateInput(WireModel):
    name: str
    use_when: str = ""
    loading: Literal["on_match", "always"] = "on_match"
    instructions: str
    owner_team: str
    tool_ids: list[str] = Field(default_factory=list[str])
    knowledge_bases: list[str] = Field(default_factory=list[str])
    guardrails: list[str] = Field(default_factory=list[str])
    # What the agent says when one of these guardrails refuses: a next step, not just a no.
    refusal: str = Field(default="", max_length=500)
    origin: Literal["blank", "generated", "imported", "duplicated"] = "blank"
    request_review: bool = False
    review_note: str = ""


class SkillDraftPatch(WireModel):
    name: str | None = None
    use_when: str | None = None
    loading: Literal["on_match", "always"] | None = None
    instructions: str | None = None
    tool_ids: list[str] | None = None
    knowledge_bases: list[str] | None = None
    guardrails: list[str] | None = None
    refusal: str | None = Field(default=None, max_length=500)
    note: str = ""
    base_version: int


class ReviewInput(WireModel):
    note: str = ""


class DeprecateInput(WireModel):
    reason: str


class AttachInput(WireModel):
    # None attaches the latest published version, as the picker offers it.
    version: int | None = None


def _in_view(s: dict[str, Any], view: str) -> bool:
    return {
        "all": True,
        "published": s["status"] == "published",
        "always": s["loading"] == "always",
        "drafts": s["draftVersion"] is not None and s["status"] != "in_review",
        "in_review": s["status"] == "in_review",
        "deprecated": s["status"] == "deprecated",
        "unused": s["usedBy"] == 0,
    }[view]


@router.get("/v1/skills", response_model=Envelope[SkillList])
async def list_skills(
    *,
    request: Request,
    rt: Rt,
    view: Literal["all", "published", "always", "drafts", "in_review", "deprecated", "unused"] = "all",
    page_no: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: str | None = None,
) -> JSONResponse:
    pins = await _pinning(rt)
    rows = [await row_view(rt, r, pins) for r in await skills(rt).rows()]
    if search:
        s = search.lower()
        rows = [x for x in rows if s in x["name"].lower() or s in x["useWhen"].lower() or s in x["slug"]]
    counts = {v: sum(1 for x in rows if _in_view(x, v)) for v in VIEWS}
    facet_cols = ("status", "ownerTeam", "origin", "loading")
    facets: dict[str, dict[str, int]] = {c: {} for c in facet_cols}
    for x in rows:
        for c in facet_cols:
            facets[c][x[c]] = facets[c].get(x[c], 0) + 1
    rows = [x for x in rows if _in_view(x, view)]
    for c in facet_cols:
        if wanted := request.query_params.getlist(c):
            rows = [x for x in rows if x[c] in wanted]
    rows.sort(key=lambda x: str(x["name"]).lower())
    return ok({**page(rows, page_no, page_size), "facets": facets, "viewCounts": counts})


@router.get("/v1/skills/options", response_model=Envelope[SkillOptions])
async def skill_options(rt: Rt) -> JSONResponse:
    """What a skill may name: the tools the directory offers, the knowledge bases agents hold, and owner teams."""
    reg = agent_registry(rt)
    specs = [(await reg.version(r["id"], int(r["version"])))["spec"] for r in await reg.rows()]
    tools = [
        {"toolId": t["id"], "name": t["name"], "module": t["server"], "system": t["server"], "access": t["access"]}
        for t in await known_tools(rt)
    ]
    held: list[Any] = [k for s in specs for k in cast(list[Any], s.get("collections") or [])]
    kbs = sorted({str(k) for k in held})
    teams = sorted({str(r["owner_team"]) for r in await skills(rt).rows()})
    return ok({"teams": teams, "tools": tools, "knowledgeBases": kbs, "limits": LIMITS})


@router.get("/v1/skills/{skill_id}", response_model=Envelope[SkillDetail])
async def get_skill(rt: Rt, skill_id: str) -> JSONResponse:
    return ok(await detail(rt, skill_id))


async def _request_review(rt: Runtime, skill_id: str, version: int, note: str, by: str) -> None:
    reg = skills(rt)
    v = await reg.version(skill_id, version)
    assert v is not None
    row = await reg.row(skill_id)
    live = await reg.version(skill_id, int(row["published_version"])) if row["published_version"] else None
    decision = await decide(
        rt, area="skills", team_id=row["team_id"], old=live["content"] if live else None, new=v["content"]
    )
    approved = not decision.review_required
    req = await agent_registry(rt).open_request(
        "skill",
        skill_id,
        version,
        note=note,
        by=by,
        body={
            "skillId": skill_id,
            "skillName": v["content"]["name"],
            "savedBy": v["saved_by"],
            **decision.record(),
            **decision.record(),
            "changes": v["changes"],
        },
        approved=approved,
    )
    if approved:
        await publish(rt, req, "auto-approve (dev)")


async def changeable(rt: Runtime, me: Principal, skill_id: str, action: str) -> dict[str, Any]:
    """The skill's row once the caller may change it (auth.require_builder: the roles grid, in the team that owns
    it or, for one no team owns, the team the request acts in)."""
    row = await skills(rt).row(skill_id)
    require_builder(
        me,
        area="skills",
        team_id=row["team_id"],
        action=action,
        what=f"skill {row['slug']}",
    )
    return row


@router.post("/v1/skills", response_model=Envelope[SkillDetail], status_code=201)
async def create_skill(rt: Rt, me: Me, body: SkillCreateInput) -> JSONResponse:
    require_builder(me, area="skills", team_id=me.team_id, action="create", what="a skill")
    content = await check_content(rt, body.model_dump(by_alias=True))
    sid = await skills(rt).create(
        content, owner_team=body.owner_team, team_id=me.team_id or "", origin=body.origin, by=me.email
    )
    if body.request_review:
        await _request_review(rt, sid, 1, body.review_note, me.email)
    return ok(await detail(rt, sid), 201)


@router.put("/v1/skills/{skill_id}/draft", response_model=Envelope[SkillDetail])
async def save_skill_draft(rt: Rt, me: Me, skill_id: str, body: SkillDraftPatch) -> JSONResponse:
    """Edits the newest draft, or opens the next version on top of the published one. 409 when `baseVersion` is
    not the newest version, or the skill is deprecated or in review."""
    reg = skills(rt)
    row = await changeable(rt, me, skill_id, "edit")
    if row["deprecated_reason"]:
        raise Conflict("The skill is deprecated; it takes no new versions.", code="skill_deprecated")
    if body.base_version != row["version"]:
        raise Conflict(
            f"v{row['version']} was saved after v{body.base_version}; reload and edit again.", code="stale_base"
        )
    if any(r["status"] == "pending" for r in await agent_registry(rt).requests("skill", skill_id)):
        raise Conflict("The newest version is in review; decide the review first.", code="review_open")
    newest = await reg.version(skill_id, int(row["version"]))
    assert newest is not None
    merged = {**newest["content"], "toolIds": [t["toolId"] for t in newest["content"]["tools"]]}
    merged |= body.model_dump(by_alias=True, exclude_none=True, exclude={"note", "base_version"})
    merged.pop("slug", None)
    await reg.save_draft(skill_id, await check_content(rt, merged), by=me.email, note=body.note)
    return ok(await detail(rt, skill_id))


@router.post("/v1/skills/{skill_id}/publish-requests", response_model=Envelope[SkillDetail], status_code=201)
async def request_skill_publish(rt: Rt, me: Me, skill_id: str, body: ReviewInput) -> JSONResponse:
    """Opens a publish request for the newest draft, decided like an agent publish (by someone other than who asked
    or saved it); approved at once under the dev auto-approve setting."""
    await changeable(rt, me, skill_id, "publish")
    d = await detail(rt, skill_id)
    if not d["publishCheck"]["canRequest"]:
        raise ValidationFailed(" ".join(d["publishCheck"]["blockers"]), code="cannot_request")
    await _request_review(rt, skill_id, int(d["version"]), body.note, me.email)
    return ok(await detail(rt, skill_id), 201)


@router.post("/v1/skills/{skill_id}/deprecate", response_model=Envelope[SkillDetail])
async def deprecate_skill(rt: Rt, me: Me, skill_id: str, body: DeprecateInput) -> JSONResponse:
    if not body.reason.strip():
        raise ValidationFailed("Say why the skill is deprecated.", code="reason_required")
    await changeable(rt, me, skill_id, "deprecate")
    await skills(rt).deprecate(skill_id, body.reason.strip(), by=me.email)
    return ok(await detail(rt, skill_id))


@router.delete("/v1/skills/{skill_id}", status_code=204, response_class=Response)
async def delete_skill(rt: Rt, me: Me, skill_id: str) -> Response:
    """Refused (403) unless the caller created the skill or is an admin of its team, and (409) while it is pinned.
    Who deleted it is logged; agents-service has no audit table yet."""
    row = await skills(rt).row(skill_id)
    require_owner_or_admin(
        me, area="skills", team_id=row["team_id"], created_by=row["created_by"] or "", what=row["slug"]
    )
    require_unpinned(await pinned_by(rt, skill_id), row["slug"])
    await skills(rt).delete(skill_id)
    await TemplateCopies(rt.db).removed_record("skill", skill_id)
    log.info("skill_deleted", skill=skill_id, slug=row["slug"], by=me.email)
    return Response(status_code=204)


@router.get("/v1/agents/{agent_id}/skills", response_model=Envelope[AgentSkills])
async def get_agent_skills(rt: Rt, agent_id: str) -> JSONResponse:
    return ok(await agent_skills(rt, agent_id))


@router.get("/v1/agents/{agent_id}/skills/options", response_model=Envelope[OptionsPage])
async def agent_skill_options(  # noqa: PLR0917 - FastAPI reads each query parameter from the signature
    rt: Rt,
    agent_id: str,
    search: str = "",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ids: Annotated[list[str] | None, Query()] = None,
    # The same member order as every other loading field: typing caches Literal types by their members, so a
    # reordered twin makes the OpenAPI enum order depend on which module was imported first.
    loading: Literal["on_match", "always"] | None = None,
) -> JSONResponse:
    """The agent page's skill picker (c-136): published, live skills the agent does not hold, searched and limited in
    the query; one that needs a tool or knowledge base the agent lacks is offered disabled with the reason. `loading`
    keeps always-on or on-match skills, also in the query (the published version's mode is kept on the row)."""
    agents = agent_registry(rt)
    spec = (await agents.version(agent_id, int((await agents.row(agent_id))["version"])))["spec"]
    held = [str(p["skillId"]) for p in cast(list[dict[str, Any]], spec.get("skillPins") or [])]
    reg = skills(rt)
    offset, window = options_window(None if ids else cursor, limit)
    rows = await reg.attachable(search, held, offset, window, ids=ids, loading=loading)
    opts: list[dict[str, Any]] = []
    for r in rows:
        v = await reg.version(r["id"], int(r["published_version"] or r["version"]))
        content = cast(dict[str, Any], (v or {}).get("content") or {})
        missing = missing_for(content, spec)
        hint = f"v{r['published_version']} · {content.get('useWhen', '')}"
        reason = f"Needs {', '.join(missing)}; grant them on this agent first." if missing else None
        opts.append({"id": r["id"], "label": content.get("name", r["slug"]), "hint": hint, "disabled": reason})
    return ok(options_page(opts, offset, limit))


@router.put("/v1/agents/{agent_id}/skills/{skill_id}", response_model=Envelope[AgentSkills])
async def attach_skill(rt: Rt, me: Me, agent_id: str, skill_id: str, body: AttachInput) -> JSONResponse:
    """Attaches the skill at `version`, or moves its pin there, as a new draft agent version; it serves once that
    version is published (spec 11 5.4)."""
    reg = agent_registry(rt)
    row = await agent_changeable(rt, me, agent_id, "attach a skill to")
    spec = dict((await reg.version(agent_id, int(row["version"])))["spec"])
    version = body.version
    if version is None:
        found = await skills(rt).find(skill_id)
        if found is None or found["published_version"] is None:
            raise NotFound(f"Published skill {skill_id}")
        version = int(found["published_version"])
    spec["skillPins"] = await pin(rt, spec, skill_id, version, by=me.email, at=now_iso())
    await reg.save(agent_id, spec, by=me.email, note=f"Attached {skill_id} v{version}")
    return ok(await agent_skills(rt, agent_id))


@router.delete("/v1/agents/{agent_id}/skills/{skill_id}", response_model=Envelope[AgentSkills])
async def detach_skill(rt: Rt, me: Me, agent_id: str, skill_id: str) -> JSONResponse:
    reg = agent_registry(rt)
    row = await agent_changeable(rt, me, agent_id, "detach a skill from")
    spec = dict((await reg.version(agent_id, int(row["version"])))["spec"])
    held: list[dict[str, Any]] = list(spec.get("skillPins") or [])
    pins = [p for p in held if p["skillId"] != skill_id]
    if len(pins) == len(held):
        raise NotFound(f"Skill {skill_id} on {agent_id}")
    spec["skillPins"] = pins
    await reg.save(agent_id, spec, by=me.email, note=f"Detached {skill_id}")
    return ok(await agent_skills(rt, agent_id))
