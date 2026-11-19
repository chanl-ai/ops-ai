"""/v1/references: what an agent's brief or a skill's steps can mention with @ (app/references.py).

The tools directory (tools-service) and the knowledge bases (kb-service) are read with nothing open, between the
transaction that checks the caller against the agent or skill and the one that reads this service's own rows.
"""

from __future__ import annotations

import contextlib
from typing import Annotated, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ops_access import can
from ops_contracts.skill_run import RefKind
from ops_service_kit.errors import Forbidden, NotFound, Unprocessable, ValidationFailed
from ops_service_kit.http import Envelope, In, Json, JsonList, options_page, options_window
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger
from ops_service_kit.narrow import json_list, json_object
from ops_store import isolation

from ...activities.knowledge import KnowledgeUnavailable
from ...activities.tool_directory import ToolsUnavailable
from ...app import references
from ...app.references import Candidate, Context, SkillNeeds
from ...app.skill_content import runs_of
from ...store.agent_registry import digest_of
from ..agent_registry import AgentSpec
from ..agent_registry import registry as agent_registry
from ..auth import Principal, caller_of, principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import ReferenceAdded, ReferenceSearch
from ..skills import content_of, pin, skills, tool_ids
from .agents import (
    _check_knowledge as check_knowledge,  # pyright: ignore[reportPrivateUsage]
)
from .agents import (
    _checked_tools as checked_tools,  # pyright: ignore[reportPrivateUsage]
)
from .agents import changeable
from .tool_catalog import directory_tools, known_tools

log = get_logger("ops_agents.references")

router = APIRouter()
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

# The kinds this service stores, which its store searches and cuts; the others come whole from another service.
STORED: frozenset[RefKind] = frozenset({"skill", "agent"})
# The roles-grid area whose view cell lets a caller see each kind.
AREAS: dict[RefKind, str] = {
    "tool": "tools",
    "knowledge": "knowledge",
    "skill": "skills",
    "agent": "agents",
    "workflow": "workflows",
}


def _viewable(me: Principal, team: str | None) -> set[RefKind]:
    """The kinds the caller may see in `team`: the view cell of each kind's area."""
    seen: set[RefKind] = set()
    for kind, area in AREAS.items():
        try:
            can(caller_of(me), area, "view", team=team, what=f"the team's {area}", code="forbidden")
        except Forbidden:
            continue
        seen.add(kind)
    return seen


def _held(spec: Json) -> dict[RefKind, frozenset[str]]:
    """What an agent version holds, by kind."""
    granted = [str(t) for t in json_list(spec.get("toolIds"))]
    return {
        "tool": frozenset(t for t in granted if not t.startswith(("agent:", "workflow:"))),
        "agent": frozenset(t.removeprefix("agent:") for t in granted if t.startswith("agent:")),
        "workflow": frozenset(t.removeprefix("workflow:") for t in granted if t.startswith("workflow:")),
        "knowledge": frozenset(str(k) for k in json_list(spec.get("collections"))),
        "skill": frozenset(str(json_object(p).get("skillId")) for p in json_list(spec.get("skillPins"))),
    }


async def _context(rt: Runtime, for_agent: str | None, for_skill: str | None) -> tuple[Context, str | None]:
    """The agent or skill being edited with what it holds, and the team that owns it."""
    if for_agent is not None:
        agents = agent_registry(rt)
        row = await agents.row(for_agent)
        spec = (await agents.version(for_agent, row.version)).spec
        return Context("agent", for_agent, str(spec.get("name") or row.slug), _held(spec)), row.team_id
    assert for_skill is not None
    reg = skills(rt)
    found = await reg.row(for_skill)
    newest = await reg.version(for_skill, found.version)
    content = newest.content if newest is not None else {}
    named: dict[RefKind, frozenset[str]] = {
        "tool": frozenset(str(json_object(t).get("toolId")) for t in json_list(content.get("tools"))),
        "knowledge": frozenset(str(k) for k in json_list(content.get("knowledgeBases"))),
    }
    return Context("skill", for_skill, str(content.get("name") or found.slug), named), found.team_id


@router.get("/v1/references", response_model=Envelope[ReferenceSearch])
async def references_search(  # noqa: PLR0917 - FastAPI reads each query parameter from the signature
    rt: Rt,
    me: Me,
    for_agent: Annotated[str | None, Query(alias="forAgent")] = None,
    for_skill: Annotated[str | None, Query(alias="forSkill")] = None,
    search: str = "",
    kind: RefKind | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
    ids: Annotated[list[str] | None, Query(max_length=references.MAX_IDS)] = None,
) -> JSONResponse:
    """What the agent (`forAgent`) or the skill (`forSkill`) can mention, grouped by kind: tools, knowledge bases,
    skills, agents and workflows of its team. Exactly one of the two is given (400 `validation_failed`).

    Searching (`search`, `limit` items a group; with `kind` one group, continued by `cursor`) is for people who may
    edit it: agents: edit or skills: edit in its team (403 `forbidden`). With `ids` (`kind:id`, repeated) it answers
    the labels of what a saved text already names, for anyone who may read: one that is not found, not offered any
    more or not visible is absent. Either way a kind whose view right the caller lacks in that team is left out, and
    another team's skill or agent is never listed. An item says whether the agent holds it (`held`) and, when it
    does not, what inserting it adds (`adds`)."""
    if (for_agent is None) == (for_skill is None):
        raise ValidationFailed("Name the agent or the skill the references are for: forAgent or forSkill, not both.")
    async with isolation.request_transaction():
        ctx, owner = await _context(rt, for_agent, for_skill)
        team = owner or me.team_id or None
        if ids is None:
            can(caller_of(me), f"{ctx.of}s", "edit", team=team, what=ctx.name, code="forbidden")
        kinds = _viewable(me, team)
    wanted = references.wanted(ids) if ids is not None else None
    offset, take = options_window(cursor if kind is not None else None, limit)
    if wanted is not None:
        # Named ids are answered whole: no page, and no search.
        offset, take = 0, references.MAX_IDS
    offered: dict[RefKind, list[Candidate]] = {}
    directory = None
    if kinds & {"tool", "workflow"}:
        # A tools service that cannot answer leaves its groups out; the other kinds are still searched.
        with contextlib.suppress(ToolsUnavailable):
            directory = await directory_tools(rt)
    if "knowledge" in kinds:
        with contextlib.suppress(KnowledgeUnavailable):
            offered["knowledge"] = [Candidate("knowledge", b.id, b.name) for b in await rt.kbs().bases()]
    async with isolation.request_transaction():
        if directory is not None:
            for t in await known_tools(rt, listed=directory):
                tool_id = str(t["id"])
                if tool_id.startswith("workflow:"):
                    offered.setdefault("workflow", []).append(
                        Candidate("workflow", tool_id.removeprefix("workflow:"), str(t["name"]))
                    )
                elif not tool_id.startswith("agent:"):
                    label, approval = str(t.get("title") or t["name"]), bool(t.get("requiresApproval"))
                    offered.setdefault("tool", []).append(Candidate("tool", tool_id, label, str(t["server"]), approval))
        # Skills and agents are this service's rows: searched and cut in the store, in the owning team only.
        if "skill" in kinds and team:
            skip = ctx.id if ctx.of == "skill" else None
            found = await skills(rt).search_team(
                team, search, offset, take, ids=wanted.get("skill", []) if wanted is not None else None, skip=skip
            )
            offered["skill"] = [Candidate("skill", i, name, hint or None) for i, name, hint in found]
        if "agent" in kinds:
            skip = ctx.id if ctx.of == "agent" else None
            agents = await agent_registry(rt).search_published(
                team, search, offset, take, ids=wanted.get("agent", []) if wanted is not None else None, skip=skip
            )
            offered["agent"] = [Candidate("agent", i, name, hint or None) for i, name, hint in agents]
    offered = {k: v for k, v in offered.items() if k in kinds and kind in (None, k)}
    if wanted is not None:
        return ok({"groups": references.named(offered, ctx, wanted)})
    pages: dict[RefKind, tuple[list[Candidate], str | None]] = {}
    for k, rows in offered.items():
        # Another service's list is held whole, so its page starts at the offset; a store's rows already do.
        rest = rows if k in STORED else references.matching(rows, ctx, search)[offset:]
        page = options_page(rest, offset, limit)
        pages[k] = (page["data"], page["nextCursor"])
    return ok({"groups": references.grouped(pages, ctx)})


class AddReference(In):
    kind: RefKind
    id: str


async def _skill_needs(rt: Runtime, skill_id: str, team: str | None) -> tuple[SkillNeeds, int, str]:
    """What attaching the team's published skill asks of an agent, with the version and the name it is attached
    under. 422 `unknown_reference` for a skill that is not this team's, 422 `not_published` for one not live."""
    row = await skills(rt).find(skill_id)
    if row is None or row.team_id != team:
        raise Unprocessable(f"{skill_id} is not a skill of this team.", code="unknown_reference")
    if row.published_version is None or row.deprecated_reason:
        raise Unprocessable(f"{row.slug} is not published, so it cannot be added.", code="not_published")
    v = await skills(rt).version(skill_id, row.published_version)
    assert v is not None
    content = content_of(v.content)
    needs = SkillNeeds(tool_ids(content), list(content["knowledgeBases"]), sorted(runs_of(v.content)))
    return needs, row.published_version, str(content["name"])


@router.post("/v1/agents/{agent_id}/references", response_model=Envelope[ReferenceAdded])
async def add_reference(rt: Rt, me: Me, agent_id: str, body: AddReference) -> JSONResponse:
    """Grants the agent what its brief mentions, as one new draft version: a tool, an agent or a workflow joins its
    tools, a knowledge base its knowledge, a skill its skills. A skill brings the tools and knowledge bases it names
    and the skills its steps run. `added` lists everything granted; repeating the call answers `added: []` and saves
    nothing.

    403 `forbidden` without agents: edit in the agent's team or the view right of the reference's area; 422
    `unknown_reference` for something the team does not offer; 422 `not_published` for a skill, agent or workflow
    that is not live; 409 `stale_base` when the draft was saved while this ran (read the agent again and repeat)."""
    async with isolation.request_transaction():
        row = await changeable(rt, me, agent_id, "edit")
        team = row.team_id or me.team_id or None
        area = AREAS[body.kind]
        can(caller_of(me), area, "view", team=team, what=f"the team's {area}", code="forbidden")
        reg = agent_registry(rt)
        spec: Json = dict((await reg.version(agent_id, row.version)).spec)
        # What the grant is added to. A brief autosave landing before the save below would be written over, so the
        # save names this and is refused (409 `stale_base`) when the draft has moved on.
        base = (row.version, digest_of(spec))
        held = _held(spec)
        needs: dict[str, SkillNeeds] = {}
        versions: dict[str, int] = {}
        labels: dict[tuple[RefKind, str], str] = {}
        if body.kind == "skill" and body.id not in held["skill"]:
            needs[body.id], versions[body.id], labels["skill", body.id] = await _skill_needs(rt, body.id, team)
            for sub in needs[body.id].runs:
                needs[sub], versions[sub], labels["skill", sub] = await _skill_needs(rt, sub, team)
        adding = references.grants(body.kind, body.id, held, needs)
        if not adding:
            return ok({"added": [], "agentVersion": row.version})
    # tools-service and kb-service are asked with nothing open.
    tools = [f"{k}:{i}" if k in ("agent", "workflow") else i for k, i in adding if k in ("tool", "agent", "workflow")]
    bases = [i for k, i in adding if k == "knowledge"]
    async with isolation.request_transaction():
        granted = [str(t) for t in json_list(spec.get("toolIds"))]
        if tools:
            try:
                spec["toolIds"] = [*await checked_tools(rt, [*granted, *tools], granted)]
            except ValidationFailed as exc:
                code = "not_published" if exc.code == "not_published" else "unknown_reference"
                raise Unprocessable(str(exc), code=code) from exc
            for t in await known_tools(rt):
                labels["tool", str(t["id"])] = str(t.get("title") or t["name"])
    if bases:
        try:
            await check_knowledge(rt, [*held["knowledge"], *bases], list(held["knowledge"]))
        except (Unprocessable, KnowledgeUnavailable) as exc:
            raise Unprocessable(str(exc), code="unknown_reference") from exc
        spec["collections"] = [*json_list(spec.get("collections")), *bases]
        labels.update({("knowledge", b.id): b.name for b in await rt.kbs().bases()})
    async with isolation.request_transaction():
        # A skill a step runs is attached before the skill that runs it, which is refused without it.
        for skill_id in reversed([i for k, i in adding if k == "skill"]):
            try:
                pins = await pin(rt, cast(AgentSpec, spec), skill_id, versions[skill_id], by=me.email, at=now_iso())
            except NotFound as exc:
                raise Unprocessable(str(exc), code="unknown_reference") from exc
            spec["skillPins"] = cast(JsonList, [*pins])
        label = labels.get((body.kind, body.id), body.id)
        version = await reg.save(agent_id, spec, by=me.email, note=f"Added {label}", base=base)
    log.info("agent_reference_added", agent=agent_id, kind=body.kind, id=body.id, by=me.email)
    added = [references.granted(Candidate(k, i, labels.get((k, i), i))) for k, i in adding]
    return ok({"added": added, "agentVersion": version})
