"""/v1/skills and /v1/agents/{id}/skills: skills as versioned attachments an agent pins (spec 11 SK-1 to SK-10 and
SK-23 to SK-25; api/skills.py). Tests, resources, generation, import and export (SK-11 to SK-22) are not served.

A route that only reads and writes this service's database answers in one request transaction (`Tx`), so a check and
the write it guards land together or not at all. The tool directory (tools-service) and the publish-review policy
(platform-service) are read with nothing open: the options route reads the directory first, a create checks its tools
before its transaction, a draft save reads and checks in one transaction, checks its tools, then checks again and
writes in a second, and a publish request takes a transaction per store call around the policy read.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import can
from ops_agent_kernel.steps import ReturnField, SkillStep
from ops_identity.fastapi import Tx
from ops_service_kit import narrow
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Envelope, In, Json, JsonList, JsonValue, OptionsPage, options_page, options_window
from ops_service_kit.ids import now_iso
from ops_service_kit.listing import ListQuery
from ops_service_kit.logging import get_logger
from ops_store import isolation

from ...app.skill_content import runs_of
from ...store.agent_registry import digest_of, refuse_stale
from ...store.skill_list import View, menu_versions, newest_specs, offered_by, skills_page
from ...store.skills import SkillRow, SkillVersionRow
from ...store.template_copies import TemplateCopies
from ..agent_registry import AgentSpec, require_owner_or_admin
from ..agent_registry import registry as agent_registry
from ..auth import Principal, caller_in, caller_of, principal, reader_of, require_builder
from ..deps import Runtime, runtime
from ..envelope import ok
from ..publish_policy import decide
from ..schemas import AgentSkills, SkillDetail, SkillList, SkillOptions, SkillRendered
from ..skills import (
    LIMITS,
    agent_skills,
    check_content,
    content_of,
    detail,
    list_row,
    missing_for,
    pin,
    pinned_by,
    publish,
    render_published,
    require_unpinned,
    skills,
)
from .agents import changeable as agent_changeable
from .tool_catalog import directory_tools, known_tools

log = get_logger("ops_agents.skills")
# Reads take a service token holding skills:view (tools-service offers a team's skills as MCP prompts); every change
# depends on `Me`, a person or key, which refuses service tokens.
router = APIRouter(dependencies=[Depends(caller_in("skills"))])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


SuccessLine = Annotated[str, Field(min_length=1, max_length=300)]


class SkillInput(In):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: Literal["string"] = "string"
    description: str = Field(default="", max_length=500)
    required: bool = False


class SkillPartInput(In):
    """One named part of a skill, read with the skill's shared instructions."""

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(max_length=200)
    use_when: str = Field(default="", max_length=1024)
    instructions: str
    inputs: list[SkillInput] = Field(default_factory=list[SkillInput], max_length=20)
    # Some of the skill's own tools, which this part uses.
    tool_ids: list[str] = Field(default_factory=list[str])
    # The most tokens this part may hold when loaded; unset takes the reply's whole skill budget.
    budget: int | None = Field(default=None, ge=1, le=6000)


class SkillRenderInput(In):
    # The part to use, for a skill with parts.
    part: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict[str, str], max_length=20)


class SkillCreateInput(In):
    name: str
    # The name in URL form when absent; a template sets it so the copy keeps the template's id as its prompt name.
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
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
    inputs: list[SkillInput] = Field(default_factory=list[SkillInput], max_length=20)
    parts: list[SkillPartInput] = Field(default_factory=list[SkillPartInput], max_length=8)
    # A skill that runs step by step: when not to use it, its steps, the exits it may end with beside done and
    # failed (name to meaning), the results it hands back and the lines that say it went well.
    not_when: str = Field(default="", max_length=1024)
    steps: list[SkillStep] = Field(default_factory=list[SkillStep], max_length=30)
    exit: dict[str, str] = Field(default_factory=dict[str, str], max_length=8)
    returns: list[ReturnField] = Field(default_factory=list[ReturnField], max_length=12)
    success: list[SuccessLine] = Field(default_factory=list[SuccessLine], max_length=8)


class SkillDraftPatch(In):
    name: str | None = None
    use_when: str | None = None
    loading: Literal["on_match", "always"] | None = None
    instructions: str | None = None
    tool_ids: list[str] | None = None
    knowledge_bases: list[str] | None = None
    guardrails: list[str] | None = None
    refusal: str | None = Field(default=None, max_length=500)
    inputs: list[SkillInput] | None = Field(default=None, max_length=20)
    parts: list[SkillPartInput] | None = Field(default=None, max_length=8)
    not_when: str | None = Field(default=None, max_length=1024)
    steps: list[SkillStep] | None = Field(default=None, max_length=30)
    exit: dict[str, str] | None = Field(default=None, max_length=8)
    returns: list[ReturnField] | None = Field(default=None, max_length=12)
    success: list[SuccessLine] | None = Field(default=None, max_length=8)
    note: str = ""
    # The copy the change was made on: the skill's `version` and `digest` as last read. A draft is rewritten in place
    # under one version number, so the digest is what tells an old copy of it from the newest.
    base_version: int
    base_digest: str


class ReviewInput(In):
    note: str = ""


class DeprecateInput(In):
    reason: str


class AttachInput(In):
    # None attaches the latest published version, as the picker offers it.
    version: int | None = None


@router.get("/v1/skills", response_model=Envelope[SkillList])
async def list_skills(
    *,
    rt: Rt,
    caller: Annotated[Principal, Depends(reader_of("skills"))],
    _: Tx,
    q: ListQuery,
    view: View = "all",
    usable_by: Annotated[Literal["agent"] | None, Query(alias="usableBy")] = None,
    agent_id: Annotated[str | None, Query(alias="agentId")] = None,
    status: Annotated[list[str] | None, Query()] = None,
    owner_team: Annotated[list[str] | None, Query(alias="ownerTeam")] = None,
    origin: Annotated[list[str] | None, Query()] = None,
    loading: Annotated[list[str] | None, Query()] = None,
    knowledge_bases: Annotated[list[str] | None, Query(alias="knowledgeBases")] = None,
) -> JSONResponse:
    """One page of the team's skills on the shared list contract, by name then id: `search` matches the name, use-when
    or slug, `ids` names skills exactly. `view=published` rows describe the published version, its inputs and parts,
    which is what chat and the MCP prompts use; every other view describes the newest version an editor sees. `status`,
    `ownerTeam`, `origin` and `loading` filter by facet; `knowledgeBases` keeps skills naming any base given. The view
    counts and facets cover every skill the search leaves, before the view and the facet filters; the page, its counts
    and its facets are read in SQL (`store/skill_list.py`).

    Every view needs skills: view in the acting team (403 `forbidden`); `usableBy=agent` is the chat / menu's list.
    With `agentId` it keeps what that agent's skill menu setting offers (its newest version) and marks a skill needing
    a tool or knowledge base the agent lacks as `locked`, naming them in `needs`."""
    # Read from `q.filters`; declared so the document and the SDKs name them.
    del status, owner_team, origin, loading, knowledge_bases
    spec: Json | None = None
    offered = None
    if agent_id is not None:
        agents = agent_registry(rt)
        agent_row = await agents.row(agent_id)
        held = (await agents.version(agent_id, agent_row.version)).spec
        spec = held
        menu = str(held.get("skillMenu") or "team")
        # A chat's skills are its team's: the team the request acts in, else the agent's own.
        team = caller.team_id or str(agent_row.team_id or "")
        offered = offered_by(agent_id, team=team, menu=menu)
    listed, counts = await skills_page(rt.db, q, view=view, offered=offered)
    body: dict[str, Any] = {**listed, "data": [list_row(r) for r in listed["data"]]}
    if spec is not None:
        contents = await menu_versions(rt.db, [x["id"] for x in body["data"]])
        for x in body["data"]:
            needs = missing_for(content_of(contents.get(x["id"], {})), cast(AgentSpec, spec))
            x["locked"], x["needs"] = bool(needs), needs
    return ok({**body, "viewCounts": counts})


@router.get("/v1/skills/options", response_model=Envelope[SkillOptions])
async def skill_options(rt: Rt, _: Annotated[Principal, Depends(reader_of("skills"))]) -> JSONResponse:
    """What a skill may name: the tools the directory offers, the knowledge bases agents hold, and owner teams. The
    directory is read from tools-service first, with nothing open, then the rows in one transaction."""
    directory = await directory_tools(rt)
    async with isolation.request_transaction():
        tools = [
            {"toolId": t["id"], "name": t["name"], "module": t["server"], "system": t["server"], "access": t["access"]}
            for t in await known_tools(rt, listed=directory)
        ]
        specs = await newest_specs(rt.db)
        teams = sorted({r.owner_team for r in await skills(rt).rows()})
    held = [k for s in specs for k in cast(JsonList, s.get("collections") or [])]
    kbs = sorted({str(k) for k in held})
    return ok({"teams": teams, "tools": tools, "knowledgeBases": kbs, "limits": LIMITS})


@router.get("/v1/skills/{skill_id}", response_model=Envelope[SkillDetail])
async def get_skill(
    rt: Rt, skill_id: str, caller: Annotated[Principal, Depends(caller_in("skills"))], _: Tx
) -> JSONResponse:
    """The skill with its instructions and every version: skills: view in the skill's team (403 `forbidden`), the same
    right render asks for, so a person who may only chat never reads a skill's text."""
    row = await skills(rt).row(skill_id)
    can(caller_of(caller), "skills", "view", team=row.team_id, what=row.slug, code="forbidden")
    return ok(await detail(rt, skill_id))


@router.post("/v1/skills/{skill_id}/render", response_model=Envelope[SkillRendered])
async def render_skill(
    rt: Rt, skill_id: str, body: SkillRenderInput, caller: Annotated[Principal, Depends(caller_in("skills"))], _: Tx
) -> JSONResponse:
    """The published version's text with the inputs filled in, for one part when the skill has parts. A read: it
    takes a service token holding skills:view in the skill's team, as the MCP prompts call it; a person needs
    skills: view there too (403 `forbidden`). 422 `skill_not_published`, `part_required`, `unknown_part`,
    `unknown_input` or `missing_input`."""
    row = await skills(rt).row(skill_id)
    can(caller_of(caller), "skills", "view", team=row.team_id, what=row.slug, code="forbidden")
    return ok(await render_published(rt, skill_id, body.part, body.inputs))


async def _request_review(rt: Runtime, skill_id: str, version: int, note: str, by: str) -> None:
    reg = skills(rt)
    v = await reg.version(skill_id, version)
    assert v is not None
    row = await reg.row(skill_id)
    live = await reg.version(skill_id, row.published_version) if row.published_version else None
    decision = await decide(rt, area="skills", team_id=row.team_id, old=live.content if live else None, new=v.content)
    approved = not decision.review_required
    req = await agent_registry(rt).open_request(
        "skill",
        skill_id,
        version,
        note=note,
        by=by,
        body={
            "skillId": skill_id,
            "skillName": v.content["name"],
            "savedBy": v.saved_by,
            **decision.record(),
            **decision.record(),
            "changes": v.changes,
        },
        approved=approved,
    )
    if approved:
        await publish(rt, req, "auto-approve (dev)")


async def changeable(rt: Runtime, me: Principal, skill_id: str, action: str) -> SkillRow:
    """The skill's row once the caller may change it (auth.require_builder: the roles grid, in the team that owns
    it or, for one no team owns, the team the request acts in)."""
    row = await skills(rt).row(skill_id)
    require_builder(
        me,
        area="skills",
        team_id=row.team_id,
        action=action,
        what=f"skill {row.slug}",
    )
    return row


@router.post("/v1/skills", response_model=Envelope[SkillDetail], status_code=201)
async def create_skill(rt: Rt, me: Me, body: SkillCreateInput) -> JSONResponse:
    """The tools the body names are checked against tools-service's directory before the transaction opens. With
    `requestReview` the publish request follows the commit, as `POST .../publish-requests` does."""
    require_builder(me, area="skills", team_id=me.team_id, action="create", what="a skill")
    content = await check_content(rt, body.model_dump(by_alias=True), team_id=me.team_id or "")
    async with isolation.request_transaction():
        sid = await skills(rt).create(
            content, owner_team=body.owner_team, team_id=me.team_id or "", origin=body.origin, by=me.email
        )
        if not body.request_review:
            return ok(await detail(rt, sid), 201)
    await _request_review(rt, sid, 1, body.review_note, me.email)
    return ok(await detail(rt, sid), 201)


async def _editable(rt: Runtime, me: Principal, skill_id: str, base: tuple[int, str]) -> SkillVersionRow:
    """The newest version once a draft save may write it: 409 when the skill is deprecated, `base` (the version and
    digest the change was made on) is not the newest version, or the newest is in review."""
    row = await changeable(rt, me, skill_id, "edit")
    if row.deprecated_reason:
        raise Conflict("The skill is deprecated; it takes no new versions.", code="skill_deprecated")
    newest = await skills(rt).version(skill_id, row.version)
    assert newest is not None
    refuse_stale(base, row.version, newest.digest, saved_by=newest.saved_by, saved_at=newest.saved_at)
    if any(r.status == "pending" for r in await agent_registry(rt).requests("skill", skill_id)):
        raise Conflict("The newest version is in review; decide the review first.", code="review_open")
    return newest


@router.put("/v1/skills/{skill_id}/draft", response_model=Envelope[SkillDetail])
async def save_skill_draft(rt: Rt, me: Me, skill_id: str, body: SkillDraftPatch) -> JSONResponse:
    """Edits the newest draft, or opens the next version on top of the published one. 409 `stale_base` when
    `baseVersion` and `baseDigest` are not the newest copy (its details name who saved it and when); 409 too when the
    skill is deprecated or in review. The checks run again in the transaction that writes, after the tools are checked
    against tools-service with nothing open, so a save landing in between answers `stale_base`."""
    reg = skills(rt)
    base = (body.base_version, body.base_digest)
    async with isolation.request_transaction():
        newest = await _editable(rt, me, skill_id, base)
        owner = (await reg.row(skill_id)).team_id
    tools = narrow.a_list(newest.content["tools"], "tools")
    merged: dict[str, JsonValue] = {
        **newest.content,
        "toolIds": [narrow.an_object(t, "tool")["toolId"] for t in tools],
    }
    merged |= body.model_dump(by_alias=True, exclude_none=True, exclude={"note", "base_version", "base_digest"})
    merged.pop("slug", None)
    content = await check_content(rt, merged, skill_id=skill_id, team_id=owner)
    async with isolation.request_transaction():
        await _editable(rt, me, skill_id, base)
        await reg.save_draft(skill_id, content, by=me.email, note=body.note, base=base)
        return ok(await detail(rt, skill_id))


@router.post("/v1/skills/{skill_id}/publish-requests", response_model=Envelope[SkillDetail], status_code=201)
async def request_skill_publish(rt: Rt, me: Me, skill_id: str, body: ReviewInput) -> JSONResponse:
    """Opens a publish request for the newest draft, decided like an agent publish (by someone other than who asked
    or saved it); approved at once under the dev auto-approve setting. Off the request transaction: the team's
    publish-review policy is read from platform-service between the reads and the writes."""
    await changeable(rt, me, skill_id, "publish")
    d = await detail(rt, skill_id, fresh=True)
    if not d["publishCheck"]["canRequest"]:
        raise ValidationFailed(
            " ".join(d["publishCheck"]["blockers"]),
            code="cannot_request",
            details={"problems": d["publishCheck"]["problems"]},
        )
    await _request_review(rt, skill_id, int(d["version"]), body.note, me.email)
    return ok(await detail(rt, skill_id), 201)


@router.post("/v1/skills/{skill_id}/deprecate", response_model=Envelope[SkillDetail])
async def deprecate_skill(rt: Rt, me: Me, _: Tx, skill_id: str, body: DeprecateInput) -> JSONResponse:
    if not body.reason.strip():
        raise ValidationFailed("Say why the skill is deprecated.", code="reason_required")
    await changeable(rt, me, skill_id, "deprecate")
    await skills(rt).deprecate(skill_id, body.reason.strip(), by=me.email)
    return ok(await detail(rt, skill_id))


@router.delete("/v1/skills/{skill_id}", status_code=204, response_class=Response)
async def delete_skill(rt: Rt, me: Me, _: Tx, skill_id: str) -> Response:
    """Refused (403) unless the caller created the skill or is an admin of its team, and (409) while it is pinned.
    Who deleted it is logged; agents-service has no audit table yet."""
    row = await skills(rt).row(skill_id)
    require_owner_or_admin(me, area="skills", team_id=row.team_id, created_by=row.created_by or "", what=row.slug)
    require_unpinned(await pinned_by(rt, skill_id), row.slug)
    await skills(rt).delete(skill_id)
    await TemplateCopies(rt.db).removed_record("skill", skill_id)
    log.info("skill_deleted", skill=skill_id, slug=row.slug, by=me.email)
    return Response(status_code=204)


@router.get("/v1/agents/{agent_id}/skills", response_model=Envelope[AgentSkills])
async def get_agent_skills(
    rt: Rt, agent_id: str, _: Annotated[Principal, Depends(reader_of("skills"))], __: Tx
) -> JSONResponse:
    return ok(await agent_skills(rt, agent_id))


@router.get("/v1/agents/{agent_id}/skills/options", response_model=Envelope[OptionsPage])
async def agent_skill_options(  # noqa: PLR0917 - FastAPI reads each query parameter from the signature
    rt: Rt,
    agent_id: str,
    _: Annotated[Principal, Depends(reader_of("skills"))],
    __: Tx,
    search: str = "",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ids: Annotated[list[str] | None, Query()] = None,
    # The same member order as every other loading field: typing caches Literal types by their members, so a
    # reordered twin makes the OpenAPI enum order depend on which module was imported first.
    loading: Literal["on_match", "always"] | None = None,
) -> JSONResponse:
    """The agent page's skill picker: published, live skills the agent does not hold, searched and limited in
    the query; one that needs a tool or knowledge base the agent lacks is offered disabled with the reason. `loading`
    keeps always-on or on-match skills, also in the query (the published version's mode is kept on the row)."""
    agents = agent_registry(rt)
    spec = (await agents.version(agent_id, (await agents.row(agent_id)).version)).spec
    held = [str(p["skillId"]) for p in cast(list[Json], spec.get("skillPins") or [])]
    reg = skills(rt)
    offset, window = options_window(None if ids else cursor, limit)
    rows = await reg.attachable(search, held, offset, window, ids=ids, loading=loading)
    opts: list[Json] = []
    for r in rows:
        v = await reg.version(r.id, r.published_version or r.version)
        content = v.content if v is not None else {}
        missing = missing_for(content_of(content), cast(AgentSpec, spec))
        hint = f"v{r.published_version} · {content.get('useWhen', '')}"
        reason = f"Needs {', '.join(missing)}; grant them on this agent first." if missing else None
        opts.append({"id": r.id, "label": content.get("name", r.slug), "hint": hint, "disabled": reason})
    return ok(options_page(opts, offset, limit))


@router.put("/v1/agents/{agent_id}/skills/{skill_id}", response_model=Envelope[AgentSkills])
async def attach_skill(rt: Rt, me: Me, _: Tx, agent_id: str, skill_id: str, body: AttachInput) -> JSONResponse:
    """Attaches the skill at `version`, or moves its pin there, as a new draft agent version; it serves once that
    version is published (spec 11 5.4)."""
    reg = agent_registry(rt)
    row = await agent_changeable(rt, me, agent_id, "attach a skill to")
    spec = dict((await reg.version(agent_id, row.version)).spec)
    # The copy the pin is added to: a save landing before the one below is never written over (409 `stale_base`).
    base = (row.version, digest_of(spec))
    version = body.version
    if version is None:
        found = await skills(rt).find(skill_id)
        if found is None or found.published_version is None:
            raise NotFound(f"Published skill {skill_id}")
        version = found.published_version
    pins = await pin(rt, cast(AgentSpec, spec), skill_id, version, by=me.email, at=now_iso())
    spec["skillPins"] = cast(JsonList, [*pins])
    await reg.save(agent_id, spec, by=me.email, note=f"Attached {skill_id} v{version}", base=base)
    return ok(await agent_skills(rt, agent_id))


@router.delete("/v1/agents/{agent_id}/skills/{skill_id}", response_model=Envelope[AgentSkills])
async def detach_skill(rt: Rt, me: Me, _: Tx, agent_id: str, skill_id: str) -> JSONResponse:
    reg = agent_registry(rt)
    row = await agent_changeable(rt, me, agent_id, "detach a skill from")
    spec = dict((await reg.version(agent_id, row.version)).spec)
    base = (row.version, digest_of(spec))
    # A pin that is not an object, or names no skill, raises as indexing it did.
    held = narrow.a_list(spec.get("skillPins") or [], "skill pins")
    pins: JsonList = [p for p in held if narrow.an_object(p, "skill pin")["skillId"] != skill_id]
    if len(pins) == len(held):
        raise NotFound(f"Skill {skill_id} on {agent_id}")
    # A skill another attached skill runs as a step stays while that one is attached.
    users = [
        str(p.get("name") or p["skillId"])
        for p in (narrow.an_object(p, "skill pin") for p in pins)
        if skill_id in runs_of(p)
    ]
    if users:
        raise Conflict(
            f"{', '.join(users)} runs this skill as a step; detach {'it' if len(users) == 1 else 'them'} first.",
            code="skill_in_use_by_skill",
        )
    spec["skillPins"] = pins
    await reg.save(agent_id, spec, by=me.email, note=f"Detached {skill_id}", base=base)
    return ok(await agent_skills(rt, agent_id))
