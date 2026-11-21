"""Skills as versioned attachments (spec 11): the views the console's skills pages and agent page
read, the checks on a skill's content, the publish an approval runs, and the pin check an attach runs.

An agent version snapshots each pinned skill version (`skillPins[]`: id, version, name, slug, useWhen, loading,
instructions, guardrails, tokens, toolIds, knowledgeBases), so the runtime serves the pin with no lookup per turn.
Not built yet (spec 11 sections 4.4, 4.5, 5.6, 5.7): skill tests, load counts, generation, import and export; the
views return those as empty and the docs page says so.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast

from ops_access import team_on
from ops_agent_kernel.types import Skill as KernelSkill
from ops_contracts.chat import SkillPick
from ops_contracts.skill_run import Ref, SkillProgram, SkillStep
from ops_service_kit import narrow
from ops_service_kit.errors import Conflict, NotFound, Unprocessable, ValidationFailed
from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.logging import get_logger

from ..activities.catalog import AgentDefinition, kernel_skills
from ..activities.tool_directory import ToolsUnavailable
from ..app import skill_content, skill_text
from ..app.skill_content import KnownSkill, Problem
from ..store.agent_registry import PublishRequestRow
from ..store.skill_list import pinning_agents, published_pinning
from ..store.skills import SkillRegistry, SkillRow, SkillVersionRow, slug_of
from ..store.tenancy import NoTenantError
from .agent_registry import SEED_BY, SEED_TEAM, AgentSpec, SkillPin, seed_agent_version
from .agent_registry import registry as agent_registry
from .child_runs import published_workflows
from .deps import Runtime
from .platform_policies import PolicyUnread
from .routers.tool_catalog import known_tools
from .step_shapes import ServiceLookups

log = get_logger("ops_agents.skills")
MAX_PER_TURN = 2
MAX_ATTACHED = 12
TOKEN_BUDGET = 6000
# Always-on bodies an agent holds, together; counted apart from TOKEN_BUDGET so they cannot starve on-match loads.
ALWAYS_BUDGET = 2000
USE_WHEN_MAX = 1024
NAME_MAX = 200
INSTRUCTIONS_MAX = 24000
MAX_PARTS = 8
# The shared instructions a skill with parts reads before any part, at four characters a token (1,000 tokens).
OVERVIEW_MAX = 4000
LIMITS: dict[str, int] = {
    "maxPerTurn": MAX_PER_TURN,
    "maxAttached": MAX_ATTACHED,
    "tokenBudget": TOKEN_BUDGET,
    "useWhenMaxChars": USE_WHEN_MAX,
}

# The team setting that refuses a write behind a condition the agent decides (ops_access.policies).
STRICT_KEY = "skillPublishStrict"


def skills(rt: Runtime) -> SkillRegistry:
    return SkillRegistry(rt.db)


class _TeamSkills:
    """The team's skills as a save of steps reads them (app/skill_content.py)."""

    def __init__(self, rt: Runtime) -> None:
        self.reg = skills(rt)

    async def skill(self, skill_id: str) -> KnownSkill | None:
        row = await self.reg.find(skill_id)
        if row is None:
            return None
        v = await self.reg.version(skill_id, row.published_version) if row.published_version else None
        return KnownSkill(
            id=row.id,
            name=str(v.content["name"]) if v is not None else row.slug,
            team_id=row.team_id,
            published=v is not None,
            deprecated=bool(row.deprecated_reason),
            runs=skill_content.runs_of(v.content) if v is not None else frozenset(),
        )

    async def running(self, skill_id: str, team_id: str) -> list[str]:
        held = await self.reg.published_in(team_id)
        return [
            str(v.content["name"]) for r, v in held if r.id != skill_id and skill_id in skill_content.runs_of(v.content)
        ]


async def check_content(rt: Runtime, fields: Json, *, skill_id: str | None = None, team_id: str = "") -> Json:
    """A version's content, normalised; refused when the model could never choose it, it names a tool the directory
    does not offer, or its steps could not run. The tools are kept as references with the directory's names and
    access. `skill_id` is the skill being saved (None for a new one) and `team_id` the team that owns it: a step may
    run only another published skill of that team."""
    name = str(fields.get("name") or "").strip()
    loading = str(fields.get("loading") or "on_match")
    use_when = str(fields.get("useWhen") or "").strip()
    if not name:
        raise ValidationFailed("Name the skill.", code="no_name")
    if len(name) > NAME_MAX:
        raise ValidationFailed(f"The name is at most {NAME_MAX} characters.", code="name_too_long")
    if len(str(fields.get("instructions") or "")) > INSTRUCTIONS_MAX:
        raise ValidationFailed(
            f"The instructions are at most {INSTRUCTIONS_MAX:,} characters.", code="instructions_too_long"
        )
    if loading not in ("on_match", "always"):
        raise ValidationFailed(f"Loading is on_match or always, not {loading}.", code="bad_loading")
    if loading == "on_match" and not use_when:
        raise ValidationFailed(
            "An on-match skill needs a use-when line: it is what the model reads to load it.", code="no_use_when"
        )
    if len(use_when) > USE_WHEN_MAX:
        raise ValidationFailed(f"The use-when line is at most {USE_WHEN_MAX} characters.", code="use_when_too_long")
    source = fields.get("source")
    has_parts = bool(narrow.entries(fields.get("parts")))
    if isinstance(source, str):
        # Written as text: the reader makes the steps, and nothing it reads refuses the save.
        if len(source) > INSTRUCTIONS_MAX:
            raise ValidationFailed(
                f"The text is at most {INSTRUCTIONS_MAX:,} characters.", code="instructions_too_long"
            )
        if not source.strip():
            raise ValidationFailed("Write the skill's instructions.", code="no_instructions")
        source = skill_text.normalised(source)
        program = await _program_of_text(
            rt, source, fields, team_id=team_id, skill_id=skill_id, loading=loading, has_parts=has_parts
        )
        # A text read as steps reaches the model one step at a time (`do`), so the instructions keep nothing: a copy
        # would put every path into every step's prompt. A text with no steps is the instructions.
        fields = {**fields, "instructions": "" if program is not None and program.steps else source}
        refs = Ref.found_in(source)
        step_tools = list(dict.fromkeys(g for r in refs if (g := r.grant) is not None))
        step_bases = list(dict.fromkeys(r.id for r in refs if r.kind == "knowledge"))
    else:
        program = await skill_content.checked(
            fields,
            skill_id=skill_id,
            team_id=team_id,
            has_parts=has_parts,
            always_on=loading == "always",
            skills=_TeamSkills(rt),
        )
        # With steps the instructions are notes shared by every step, and may be empty.
        if program is None and not str(fields.get("instructions") or "").strip():
            raise ValidationFailed("Write the skill's instructions.", code="no_instructions")
        # What the steps name joins the skill's own tools and knowledge bases: the scope an agent must hold to attach
        # it.
        step_tools, step_bases = skill_content.scope(program)
    tool_ids = list(dict.fromkeys([*(str(t) for t in cast(list[Any], fields.get("toolIds") or [])), *step_tools]))
    # The directory is read per tenant, so a skill naming no tool does not need it (the start-up seed has no tenant).
    offered = {t["id"]: t for t in await known_tools(rt)} if tool_ids else {}
    if any(t not in offered for t in tool_ids):
        # A tool offered moments ago is not in the list kept for 30 s: ask once more before refusing it.
        offered = {t["id"]: t for t in await known_tools(rt, fresh=True)}
    if isinstance(source, str):
        # A mention of a tool that is gone stays in the text and its step, where the publish check finds it; it
        # joins no scope, since no agent could hold it.
        tool_ids = [t for t in tool_ids if t in offered]
    elif unknown := [t for t in tool_ids if t not in offered]:
        raise ValidationFailed(f"Unknown tools: {', '.join(unknown)}.", code="unknown_tool")
    if not isinstance(source, str):
        skill_content.refuse_unruled(program, {t: str(offered[t]["access"]) for t in tool_ids})
    slug = str(fields.get("slug") or slug_of(name))
    parts = _parts(fields.get("parts"), tool_ids, loading)
    if parts:
        await _check_overview(rt, fields, slug, parts)
    content: SkillContent = {
        "name": name,
        "slug": slug,
        "useWhen": use_when,
        "loading": loading,
        "instructions": str(fields.get("instructions") or "").strip(),
        "tools": [
            {
                "toolId": t,
                "name": offered[t]["name"],
                "module": offered[t]["server"],
                "system": offered[t]["server"],
                "access": offered[t]["access"],
            }
            for t in tool_ids
        ],
        "knowledgeBases": list(
            dict.fromkeys([*(str(k) for k in cast(list[Any], fields.get("knowledgeBases") or [])), *step_bases])
        ),
        "guardrails": [g for g in (str(x).strip() for x in cast(list[Any], fields.get("guardrails") or [])) if g],
        "resources": [],
    }
    # Kept only when written, so a version saved before the field keeps its digest.
    if refusal := str(fields.get("refusal") or "").strip():
        content["refusal"] = refusal
    if inputs := _inputs(fields.get("inputs")):
        content["inputs"] = inputs
    if parts:
        content["parts"] = parts
    if isinstance(source, str):
        content["source"] = source
    # Stored as written: the registry takes the document as JSON. The program's keys join only when set.
    return {**cast(Json, content), **skill_content.stored(program)}


def _kept_keys(fields: Json) -> Json:
    """The not-when line, endings, results and success lines the form keeps beside a text, checked as a program's
    keys: they are the form's, so a text that holds no step keeps them."""
    extra = {k: fields[k] for k in ("notWhen", "exit", "returns", "success") if fields.get(k)}
    try:
        return SkillProgram.model_validate(extra).model_dump(mode="json", by_alias=True, exclude_none=True)
    except Exception as e:
        raise ValidationFailed(str(e), code="validation_failed") from e


class SkillInputSpec(TypedDict):
    """One input a skill or a part asks for, as a version stores it."""

    name: str
    type: str
    description: str
    required: bool


class SkillPartSpec(TypedDict):
    """One named part of a skill, as a version stores it; the keys a part was saved without are left out."""

    slug: str
    name: str
    useWhen: str
    instructions: str
    inputs: NotRequired[list[SkillInputSpec]]
    toolIds: NotRequired[list[str]]
    budget: NotRequired[int]


class SkillTool(TypedDict):
    """A tool a skill names, with the directory's name and access when the version was saved."""

    toolId: str
    name: str
    module: str
    system: str
    access: str


class SkillContent(TypedDict):
    """A skill version's stored `content`, as `check_content` writes it. Read as a view of the stored document (cast,
    never rebuilt), so a version saved before a key existed reads, and fails, exactly as it did."""

    name: str
    slug: str
    useWhen: str
    loading: str
    instructions: str
    tools: list[SkillTool]
    knowledgeBases: list[str]
    guardrails: list[str]
    resources: list[JsonValue]
    refusal: NotRequired[str]
    inputs: NotRequired[list[SkillInputSpec]]
    parts: NotRequired[list[SkillPartSpec]]
    # The skill as written in the text editor; its steps are read from it (app/skill_text.py) at each save. Absent on
    # a skill saved as a list of steps.
    source: NotRequired[str]
    # A skill with steps (ops_contracts.skill_run.SkillProgram, as stored): absent on a skill without them.
    notWhen: NotRequired[str]
    steps: NotRequired[list[JsonValue]]
    exit: NotRequired[dict[str, str]]
    returns: NotRequired[list[JsonValue]]
    success: NotRequired[list[str]]


def content_of(stored: Json) -> SkillContent:
    """A version's stored content as `SkillContent`; nothing is checked or copied."""
    return cast(SkillContent, stored)


def _parts(raw: Any, tool_ids: list[str], loading: str) -> list[SkillPartSpec]:
    """The skill's named parts, each read with the shared instructions; a version saved without any keeps no key, so
    its digest is unchanged. A part's tools are some of the skill's own, so picking a part never adds scope. What is
    saved, so a part that is not an object, or parts that are a number, fail the save."""
    parts: list[SkillPartSpec] = []
    for f in (narrow.an_object(x, "part") for x in narrow.entries(raw)):
        slug = str(f.get("slug") or "").strip()
        name = str(f.get("name") or "").strip()
        use_when = str(f.get("useWhen") or "").strip()
        instructions = str(f.get("instructions") or "").strip()
        if not slug or not name or not instructions:
            raise ValidationFailed("Each part needs a slug, a name and instructions.", code="incomplete_part")
        if loading == "on_match" and not use_when:
            raise ValidationFailed(f"Part {name} needs a use-when line.", code="no_use_when")
        if any(p["slug"] == slug for p in parts):
            raise ValidationFailed(f"Two parts are named {slug}; give each its own.", code="duplicate_part")
        part_tools = list(dict.fromkeys(str(t) for t in narrow.entries(f.get("toolIds"))))
        if outside := [t for t in part_tools if t not in tool_ids]:
            raise ValidationFailed(
                f"Part {name} names {', '.join(outside)}, which the skill does not; add it to the skill's tools.",
                code="part_tool_not_in_skill",
            )
        budget = int(cast(Any, f.get("budget")) or 0)
        if budget and not 0 < budget <= TOKEN_BUDGET:
            raise ValidationFailed(f"A part's budget is 1 to {TOKEN_BUDGET:,} tokens.", code="bad_part_budget")
        if budget and (len(instructions) + 3) // 4 > budget:
            raise ValidationFailed(
                f"Part {name} is longer than its own {budget:,}-token budget; shorten it or raise the budget.",
                code="part_over_budget",
            )
        part: SkillPartSpec = {"slug": slug, "name": name, "useWhen": use_when, "instructions": instructions}
        if inputs := _inputs(f.get("inputs")):
            part["inputs"] = inputs
        if part_tools:
            part["toolIds"] = part_tools
        if budget:
            part["budget"] = budget
        parts.append(part)
    if len(parts) > MAX_PARTS:
        raise ValidationFailed(f"A skill has at most {MAX_PARTS} parts.", code="too_many_parts")
    return parts


async def _check_overview(rt: Runtime, fields: Json, slug: str, parts: list[SkillPartSpec]) -> None:
    """A skill with parts: the shared text stays short, inputs sit on the parts, and no part's assistant prompt name
    (`<skill>-<part>`) is another skill's name."""
    if len(str(fields.get("instructions") or "").strip()) > OVERVIEW_MAX:
        raise ValidationFailed(
            f"With parts, the shared instructions are at most {OVERVIEW_MAX:,} characters; move the rest into a part.",
            code="overview_too_long",
        )
    if fields.get("inputs"):
        raise ValidationFailed("A skill with parts takes its inputs on each part.", code="inputs_on_parts")
    taken = {r.slug for r in await skills(rt).rows()} - {slug}
    if clash := [f"{slug}-{p['slug']}" for p in parts if f"{slug}-{p['slug']}" in taken]:
        raise ValidationFailed(
            f"{', '.join(clash)} is already another skill's name; rename the part.", code="part_name_taken"
        )


class RenderedText(TypedDict):
    text: str
    part: NotRequired[str]
    partName: NotRequired[str]


class RenderedSkill(TypedDict):
    """`render_published`'s answer, in reply order."""

    skillId: str
    name: str
    slug: str
    version: int
    text: str
    part: NotRequired[str]
    partName: NotRequired[str]


class SkillHolds(TypedDict):
    """What an agent holds, as `missing_for` compares a skill against it."""

    toolIds: list[str]
    collections: list[str]


def render(content: SkillContent, part: str | None, given: dict[str, str]) -> RenderedText:
    """The text a person or assistant uses: the skill's instructions, or its shared instructions and one part, with
    the inputs filled in. The one place inputs become text; chat and the MCP prompts both call it.

    Raises:
        Unprocessable: `part_required` or `unknown_part` for the part, `unknown_input` for a value the skill does
            not ask for, `missing_input` naming each required input left empty.
    """
    name = str(content["name"])
    parts = content.get("parts") or []
    chosen = next((p for p in parts if p["slug"] == part), None) if part else None
    slugs = [p["slug"] for p in parts]
    if part and chosen is None:
        raise Unprocessable(f"{name} has no part {part}.", code="unknown_part", details={"parts": slugs})
    if parts and chosen is None:
        raise Unprocessable(
            f"Pick a part of {name}: {', '.join(slugs)}.", code="part_required", details={"parts": slugs}
        )
    declared = (chosen or content).get("inputs") or []
    names = [str(i["name"]) for i in declared]
    if unknown := sorted(set(given) - set(names)):
        raise Unprocessable(
            f"{name} does not take {', '.join(unknown)}.", code="unknown_input", details={"unknown": unknown}
        )
    values = {n: str(given.get(n) or "").strip() for n in names}
    if missing := [str(i["name"]) for i in declared if i.get("required") and not values[str(i["name"])]]:
        raise Unprocessable(
            f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required.",
            code="missing_input",
            details={"missing": missing},
        )
    # A skill written as text renders as written: its stored instructions are empty once the text runs as steps.
    text = text_of(cast(Json, content)) if content.get("source") is not None else str(content["instructions"])
    if chosen is not None:
        text += "\n\n" + str(chosen["instructions"])
    for n, v in values.items():
        # An optional input left empty is dropped, never left as {{name}}.
        text = text.replace("{{" + n + "}}", v)
    if filled := [f"- {n}: {v}" for n, v in values.items() if v]:
        text += "\n\nInputs:\n" + "\n".join(filled)
    out: RenderedText = {"text": text}
    if chosen:
        out["part"], out["partName"] = chosen["slug"], chosen["name"]
    return out


async def render_published(
    rt: Runtime, skill_id: str, part: str | None, given: dict[str, str], *, team: str | None = None
) -> RenderedSkill:
    """`render` on the skill's published version, never a draft. `team` is the conversation's team when a chat uses
    it: a skill another team owns is not found, whatever team the request reads as.

    Raises:
        NotFound: no such skill in the team.
        Unprocessable: `skill_not_published` when it has no published version or is deprecated; `render`'s codes.
    """
    reg = skills(rt)
    row = await reg.find(skill_id)
    if row is None or (team is not None and row.team_id != team):
        raise NotFound(f"Skill {skill_id}")
    v = await reg.version(skill_id, row.published_version) if row.published_version else None
    if v is None or row.deprecated_reason:
        raise Unprocessable(
            f"{row.slug} has no published version in use; only a published skill can be used.",
            code="skill_not_published",
        )
    content = content_of(v.content)
    name = content["name"]
    rendered = render(content, part, given)
    out: RenderedSkill = {"skillId": skill_id, "name": name, "slug": row.slug, "version": v.version, **rendered}
    return out


def _wire(content: SkillContent) -> SkillContent:
    """A version's content as the console reads it: a part saved without inputs keeps no key, so it is sent as []."""
    parts = content.get("parts")
    if not parts:
        return content
    wired: list[SkillPartSpec] = [{"inputs": [], **p} for p in parts]
    return {**content, "parts": wired}


def _inputs(raw: Any) -> list[SkillInputSpec]:
    """The skill's inputs, each name once; a version saved without any keeps no key, so its digest is unchanged. What
    is saved, so an input that is not an object, or inputs that are a number, fail the save."""
    out: dict[str, SkillInputSpec] = {}
    for f in (narrow.an_object(x, "input") for x in narrow.entries(raw)):
        name = str(f.get("name") or "").strip()
        if name and name not in out:
            out[name] = {
                "name": name,
                "type": "string",
                "description": str(f.get("description") or "").strip(),
                "required": bool(f.get("required")),
            }
    return list(out.values())


def tool_ids(content: SkillContent) -> list[str]:
    tools = list(content.get("tools") or [])
    return [str(t["toolId"]) for t in tools]


def missing_for(content: SkillContent, agent_spec: AgentSpec | SkillHolds) -> list[str]:
    """Tools and knowledge bases the skill names that the agent does not hold: a skill never adds scope."""
    tools = set(agent_spec.get("toolIds") or [])
    kbs = set(agent_spec.get("collections") or [])
    named = list(content.get("knowledgeBases") or [])
    return [t for t in tool_ids(content) if t not in tools] + [k for k in named if k not in kbs]


async def _requests(rt: Runtime, skill_id: str) -> list[PublishRequestRow]:
    return await agent_registry(rt).requests("skill", skill_id)


async def pinned_by(rt: Runtime, skill_id: str) -> list[str]:
    """Agents whose newest or published version pins the skill (the published one serves chat), and published
    workflows whose agent steps carry it (a workflow keeps the agent version it was published with). The acting
    team's agents only, as the skills list counts them."""
    names = {str(a.spec["name"]) for a in await pinning_agents(rt.db, skill_id)}
    names.update(await published_pinning(rt.db, skill_id))
    names.update(await workflows_pinning(rt, "skills", "skill_id", skill_id))
    return sorted(names)


async def workflows_pinning(rt: Runtime, field: str, key: str, value: str) -> set[str]:
    """Published workflows with an agent step whose pinned agent carries `value` under `field[].key`."""
    return (await workflows_pinning_each(rt, field, key)).get(value, set())


async def workflows_pinning_each(rt: Runtime, field: str, key: str) -> dict[str, set[str]]:
    """Each value held under `field[].key` by an agent step of a published workflow, to those workflows' labels; one
    pass over the published workflows answers for every record a page shows."""
    out: dict[str, set[str]] = {}
    if rt.graph_store is None:
        return out
    for row in await published_workflows(rt):
        d = await rt.graph_store.version(row["id"], int(row["published_version"]))
        # A workflow definition is the customer's: read loose, failing as before on a shape it never had.
        definition: Json = dict(d.definition if d else {})
        nodes = list(cast(list[Json], definition.get("nodes") or []))
        for n in nodes:
            config: Json = dict(cast(Json, n.get("config") or {}))
            agent: Json = dict(cast(Json, config.get("agent") or {}))
            held = list(cast(list[Json], agent.get(field) or []))
            if n.get("kind") == "agent_turn":
                for x in held:
                    if x.get(key) is not None:
                        out.setdefault(str(x[key]), set()).add(f"workflow {row['name']}")
    return out


def _status(row: SkillRow, pending: PublishRequestRow | None) -> str:
    if row.deprecated_reason:
        return "deprecated"
    if pending is not None and pending.version == row.version:
        return "in_review"
    return "published" if row.published_version is not None else "draft"


def _version_state(row: SkillRow, v: SkillVersionRow, requests: list[PublishRequestRow]) -> str:
    n, pub = v.version, row.published_version
    if v.published_at is not None:
        if row.deprecated_reason:
            return "deprecated"
        return "published" if n == pub else "superseded"
    mine = [r for r in requests if r.version == n]
    if any(r.status == "pending" for r in mine):
        return "in_review"
    if any(r.status == "rejected" for r in mine):
        return "rejected"
    return "draft"


class SkillListSource(TypedDict):
    """A `store.skill_list` row as `list_row` reads it (a view, cast, never rebuilt)."""

    id: str
    slug: str
    owner_team: str
    status: str
    version: int
    published_version: int | None
    used_by: int
    live_agents: int
    tokens: int
    updated_at: str
    updated_by: str
    origin: str
    pending_id: str | None
    content: SkillContent


class PartRow(TypedDict):
    slug: str
    name: str
    useWhen: str
    inputs: list[SkillInputSpec]


class SkillListRow(TypedDict):
    """One skills list row, in reply order; `locked` and `needs` only on the / menu's list for one agent."""

    id: str
    name: str
    slug: str
    useWhen: str
    loading: str
    ownerTeam: str
    status: str
    version: int
    publishedVersion: int | None
    draftVersion: int | None
    usedBy: int
    liveAgents: int
    toolCount: int
    kbCount: int
    lastEvalPassRate: float | None
    tokens: int
    updatedAt: str
    updatedBy: str
    origin: str
    inputs: list[SkillInputSpec]
    parts: list[PartRow]
    pendingReviewId: NotRequired[str]
    locked: NotRequired[bool]
    needs: NotRequired[list[str]]


def list_row(source: Json | SkillListSource) -> SkillListRow:
    """One list row from a `store.skill_list` row: the skill with the version it shows (`content`, `tokens`), its
    status, its newest pending review and how many of the team's agents pin it (`used_by`, `live_agents`)."""
    r = cast(SkillListSource, source)
    content = r["content"]
    return cast(
        SkillListRow,
        {
            "id": r["id"],
            "name": content["name"],
            "slug": r["slug"],
            "useWhen": content["useWhen"],
            "loading": content["loading"],
            "ownerTeam": r["owner_team"],
            "status": r["status"],
            "version": r["version"],
            "publishedVersion": r["published_version"],
            "draftVersion": r["version"] if r["version"] != r["published_version"] else None,
            "usedBy": int(r["used_by"]),
            "liveAgents": int(r["live_agents"]),
            "toolCount": len(content["tools"]),
            "kbCount": len(content["knowledgeBases"]),
            # Skill tests are not built yet (spec 11 4.4), so there is no pass rate to report.
            "lastEvalPassRate": None,
            "tokens": r["tokens"],
            "updatedAt": r["updated_at"],
            "updatedBy": r["updated_by"],
            "origin": r["origin"],
            "inputs": content.get("inputs") or [],
            "parts": [
                {"slug": p["slug"], "name": p["name"], "useWhen": p["useWhen"], "inputs": p.get("inputs") or []}
                for p in content.get("parts") or []
            ],
            **({"pendingReviewId": r["pending_id"]} if r["pending_id"] else {}),
        },
    )


def over_budget(v: SkillVersionRow) -> str | None:
    """Why a version could never load because of its size, or None: an on-match body (with parts, the shared text and
    its longest part) past the reply's skill budget, an always-on body past the always-on budget."""
    budget = TOKEN_BUDGET if v.content["loading"] == "on_match" else ALWAYS_BUDGET
    if v.tokens <= budget:
        return None
    return (
        f"v{v.version} is {v.tokens:,} tokens; a {v.content['loading']} body over {budget:,} could never "
        "load. Shorten it."
    )


class SkillUsage(TypedDict):
    agentId: str
    agentName: str
    agentTeamId: str | None
    agentAvailability: str
    pinnedVersion: int
    latestPublished: int | None
    upgradeAvailable: bool
    upgradeBlocked: NotRequired[str]
    loads7d: int
    share7d: int
    lastLoadedAt: str | None
    attachedAt: str
    attachedBy: str


class SkillVersionView(TypedDict):
    version: int
    state: str
    editClass: str
    note: str
    changes: list[JsonValue]
    savedBy: str
    savedAt: str
    content: SkillContent
    tokens: int
    reviewId: NotRequired[str]
    publishedAt: NotRequired[str]
    # Who made it live; who asked for the publish; who approved it (None when the team's policy let it publish without
    # a review).
    publishedBy: NotRequired[str | None]
    requestedBy: NotRequired[str | None]
    approvedBy: NotRequired[str | None]
    testRun: None


class PendingSkillReview(TypedDict):
    id: str
    version: int
    editClass: str
    approvals: int
    needed: int


class PublishCheck(TypedDict):
    canRequest: bool
    # Each problem's sentence; `problems` is the same list with where each one is.
    blockers: list[str]
    problems: list[Problem]
    # What the builder should look at and may publish with: a tool a step's sentence names and does not run.
    warnings: list[Problem]
    editClass: str
    approversNeeded: int


class SkillDetailView(SkillListRow):
    """The skill page's reply: the list row, then these, in reply order."""

    content: SkillContent
    # The text the editor shows: `content.source`, or the stored steps written as text.
    text: str
    # The newest version's stored digest: with `version`, the copy a draft save names as its base.
    digest: str
    versions: list[SkillVersionView]
    tests: list[JsonValue]
    runs: list[JsonValue]
    usage: list[SkillUsage]
    activity: Json
    provenance: Json
    pendingReview: NotRequired[PendingSkillReview]
    publishCheck: PublishCheck


async def _directory(rt: Runtime, *, fresh: bool = False) -> tuple[dict[str, str] | None, dict[str, str]]:
    """The access of each tool the tools directory offers, by id (None when it cannot answer), and each tool's name by
    its `@tool:` token, for the reader's hints."""
    try:
        rows = await known_tools(rt, fresh=fresh)
    except ToolsUnavailable:
        return None, {}
    offered = {str(t["id"]): str(t["access"]) for t in rows}
    return offered, {f"@tool:{t['id']}": str(t.get("title") or t["name"]) for t in rows if ":" not in str(t["id"])}


async def strict_publishing(rt: Runtime, team: str | None) -> bool | None:
    """Whether `team` turned skillPublishStrict on, read live from platform-service as publishReview is; None when it
    could not be read. Off with no platform URL or no tenant (the start-up seed)."""
    if team is None or rt.policies is None:
        return False
    try:
        return team_on(await rt.policies.value(STRICT_KEY), team)
    except NoTenantError:
        return False
    except PolicyUnread:
        return None


async def _bases(rt: Runtime) -> dict[str, str] | None:
    """The knowledge bases kb-service offers, id to name; None when it cannot answer."""
    try:
        return {b.id: b.name for b in await rt.kbs().bases()}
    except Exception:
        return None


async def _fields(rt: Runtime, refs: list[Ref]) -> dict[str, skill_text.Fields]:
    """What each mentioned tool returns, by its token, from its output schema in tools-service; a tool with none,
    or one tools-service cannot answer for, is left out, so its conditions are decided by the agent."""
    out: dict[str, skill_text.Fields] = {}
    lookups = ServiceLookups(rt, "", None)
    for ref in refs:
        if ref.kind != "tool" or ref.token in out:
            continue
        shape = await lookups.operation_output(ref.id)
        props = narrow.json_object(shape.get("properties")) if shape is not None else {}
        fields: dict[str, skill_text.Field] = {}
        for name, raw in props.items():
            spec = narrow.json_object(raw)
            f: skill_text.Field = {"type": str(spec.get("type") or "")}
            if enum := narrow.json_list(spec.get("enum")):
                f["enum"] = [str(e) for e in enum]
            fields[name] = f
        out[ref.token] = fields
    return out


def _plain(loading: str, has_parts: bool) -> str | None:
    """Why a text is read as plain instructions whatever it holds; None when it may run step by step."""
    if loading == "always":
        return "An always-on skill is read as plain instructions: its tools and paths are not enforced."
    if has_parts:
        return "A skill written in parts is read as plain instructions: its tools and paths are not enforced."
    return None


async def read_text(
    rt: Runtime,
    source: str,
    *,
    team_id: str,
    loading: str = "on_match",
    has_parts: bool = False,
    exits: Mapping[str, str] | None = None,
) -> skill_text.Reading:
    """The editor's read of a text it has not saved: the same reader a save runs, with what each tool returns and
    which mentions no longer exist."""
    refs = Ref.found_in(source)
    offered, labels = await _directory(rt)
    bases = await _bases(rt) if any(r.kind == "knowledge" for r in refs) else None
    labels |= {f"@knowledge:{i}": n for i, n in (bases or {}).items()}
    gone = await skill_content.missing(refs, offered, bases, team_id=team_id, skills=_TeamSkills(rt))
    return skill_text.read(
        source,
        fields=await _fields(rt, refs),
        labels=labels,
        missing=gone,
        plain=_plain(loading, has_parts),
        exits=exits,
        access=offered,
    )


async def _program_of_text(
    rt: Runtime, source: str, fields: Json, *, team_id: str, skill_id: str | None, loading: str, has_parts: bool
) -> SkillProgram | None:
    """The program a saved text reads as, with the not-when line, results and success lines the form keeps beside
    it. A step that would run a skill that runs this one, or one whose own steps run a skill, keeps the mention as
    words: the kernel starts sub-skills one level deep."""
    refs = Ref.found_in(source)
    kept_keys = _kept_keys(fields)
    declared = cast(dict[str, str], kept_keys.get("exit") or {})
    reading = skill_text.read(source, fields=await _fields(rt, refs), plain=_plain(loading, has_parts), exits=declared)
    program = reading.program
    if program is None:
        return SkillProgram.model_validate(kept_keys) if any(kept_keys.get(k) for k in skill_content.KEYS) else None
    team = _TeamSkills(rt)
    kept: list[SkillStep] = []
    for step in program.steps:
        if step.use is not None and step.use.kind == "skill":
            target = await team.skill(step.use.id)
            loops = step.use.id == skill_id or (
                target is not None and (bool(target.runs) or (skill_id or "") in target.runs)
            )
            kept.append(step.model_copy(update={"use": None}) if loops else step)
            continue
        kept.append(step)
    extra = {k: kept_keys[k] for k in ("notWhen", "returns", "success") if kept_keys.get(k)}
    try:
        return SkillProgram.model_validate(
            {
                **program.model_dump(mode="json", by_alias=True, exclude_none=True),
                "steps": [s.model_dump(mode="json", by_alias=True, exclude_none=True) for s in kept],
                **extra,
            }
        )
    except Exception as e:
        raise ValidationFailed(str(e), code="validation_failed") from e


def text_of(content: Json) -> str:
    """The skill's text for the editor: as written, or for a skill saved as a list of steps, its steps written as
    text by the same reader (`skill_text.render`)."""
    source = content.get("source")
    if isinstance(source, str):
        return skill_text.normalised(source)
    return skill_text.render(str(content.get("instructions") or ""), skill_content.program_of(content))


async def detail(rt: Runtime, skill_id: str, *, fresh: bool = False) -> SkillDetailView:
    """The skill page's reply. The publish check reads the tools directory only for a skill with steps: from the
    list kept for 30 seconds, or again from tools-service with `fresh`, as a publish request asks, so a tool removed
    moments ago cannot be published."""
    reg = skills(rt)
    row = await reg.row(skill_id)
    users = await pinning_agents(rt.db, skill_id)
    versions = await reg.versions(skill_id)
    requests = await _requests(rt, skill_id)
    by_review = {r.id: r for r in requests}
    pending = next((r for r in requests if r.status == "pending"), None)
    newest = versions[0]
    base = list_row(
        {
            **row.model_dump(),
            "content": newest.content,
            "tokens": newest.tokens,
            "status": _status(row, pending),
            "pending_id": pending.id if pending else None,
            "used_by": len(users),
            "live_agents": sum(1 for a in users if a.published_version is not None and not a.paused),
        }
    )
    problems: list[Problem] = []

    def block(kind: Any, message: str) -> None:
        problems.append({"kind": kind, "id": None, "position": None, "message": message})

    if row.deprecated_reason:
        block("deprecated", "The skill is deprecated.")
    elif newest.published_at is not None:
        block("already_published", f"v{newest.version} is already published; save a change to open a draft.")
    elif pending is not None:
        block("review_open", f"{pending.id} is already open for v{pending.version}.")
    if too_long := over_budget(newest):
        block("too_long", too_long)
    warnings: list[Problem] = []
    if (newest.content.get("steps") or newest.content.get("source") is not None) and newest.published_at is None:
        offered, labels = await _directory(rt, fresh=fresh)
        source = newest.content.get("source")
        bases = await _bases(rt) if source is not None else None
        fields = await _fields(rt, Ref.found_in(source)) if isinstance(source, str) else None
        blocking, warnings = await skill_content.publish_problems(
            newest.content,
            offered,
            team_id=row.team_id,
            skills=_TeamSkills(rt),
            bases=bases,
            fields=fields,
            labels=labels,
            strict=lambda: strict_publishing(rt, row.team_id or None),
        )
        problems += blocking
    blockers = [p["message"] for p in problems]
    latest = row.published_version
    published = next((v for v in versions if v.version == latest), None)
    usage: list[SkillUsage] = []
    for a in users:
        spec = cast(AgentSpec, dict(a.spec))
        newer = published if latest and latest > a.pinned_version else None
        blocked = missing_for(content_of(newer.content), spec) if newer else []
        held = spec.get("skillPins") or []
        pin = next((p for p in held if p["skillId"] == skill_id), None)
        usage.append(
            cast(
                SkillUsage,
                {
                    "agentId": a.id,
                    "agentName": spec["name"],
                    "agentTeamId": a.team_id,
                    "agentAvailability": "paused"
                    if a.paused
                    else "published"
                    if a.published_version is not None
                    else "not_published",
                    "pinnedVersion": a.pinned_version,
                    "latestPublished": latest,
                    "upgradeAvailable": newer is not None,
                    **(
                        {"upgradeBlocked": f"Needs {', '.join(blocked)}, which the agent does not hold."}
                        if blocked
                        else {}
                    ),
                    # Loads are not counted per agent yet.
                    "loads7d": 0,
                    "share7d": 0,
                    "lastLoadedAt": None,
                    "attachedAt": (pin.get("attachedAt") if pin is not None else None) or a.updated_at,
                    "attachedBy": (pin.get("attachedBy") if pin is not None else None) or "",
                },
            )
        )
    return cast(
        SkillDetailView,
        {
            **base,
            "content": _wire(content_of(newest.content)),
            "text": text_of(newest.content),
            "digest": newest.digest,
            "versions": [
                {
                    "version": v.version,
                    "state": _version_state(row, v, requests),
                    "editClass": "re_test",
                    "note": v.note,
                    "changes": v.changes,
                    "savedBy": v.saved_by,
                    "savedAt": v.saved_at,
                    "content": _wire(content_of(v.content)),
                    "tokens": v.tokens,
                    **({"reviewId": v.review_id} if v.review_id else {}),
                    **(
                        {
                            "publishedAt": v.published_at,
                            "publishedBy": v.published_by,
                            "requestedBy": requester(by_review.get(v.review_id or "")),
                            "approvedBy": approver(by_review.get(v.review_id or "")),
                        }
                        if v.published_at
                        else {}
                    ),
                    "testRun": None,
                }
                for v in versions
            ],
            "tests": [],
            "runs": [],
            "usage": usage,
            "activity": {"agents": [], "loadsPerDay": [], "loads30d": 0, "successRate": None, "samples": []},
            "provenance": {"origin": row.origin, "detail": "", "citations": []},
            **(
                {
                    "pendingReview": {
                        "id": pending.id,
                        "version": pending.version,
                        "editClass": "re_test",
                        "approvals": 0,
                        "needed": 1,
                    }
                }
                if pending
                else {}
            ),
            "publishCheck": {
                "canRequest": not blockers,
                "blockers": blockers,
                "problems": problems,
                "warnings": warnings,
                "editClass": "re_test",
                "approversNeeded": 1,
            },
        },
    )


async def publish(rt: Runtime, req: PublishRequestRow, by: str) -> None:
    """Publishes the request's version as `by`, who made it live. Who asked for it and who approved it are read back
    from the request by `review_id` (`requester`, `approver`)."""
    await skills(rt).publish(req.subject_id, int(req.version), by=by, review_id=req.id)


def requester(req: PublishRequestRow | None) -> str | None:
    """Who asked for a published version's publish; None when no request published it (a seed)."""
    return str(req.requested_by) if req is not None and req.requested_by else None


def approver(req: PublishRequestRow | None) -> str | None:
    """Who approved a published version: the request's decider when its policy asked for a review; None when the
    policy let it publish without one (`reviewRequired` false) or no request published it (a seed)."""
    if req is None or req.status != "approved" or not req.body.get("reviewRequired", True):
        return None
    return str(req.decided_by) if req.decided_by else None


def review_record(live: SkillVersionRow | None, v: SkillVersionRow, warnings: Sequence[Problem]) -> Json:
    """What a skill publish request keeps for its reviewer: the published version it replaces, both texts as the
    editor shows them (`text_of`, so a skill saved as steps compares as text), the hints on the new text's lines, and
    the tools and knowledge bases it adds."""
    before = content_of(live.content) if live else None
    after = content_of(v.content)
    had_tools = set(tool_ids(before)) if before else set[str]()
    had_bases = set(before["knowledgeBases"]) if before else set[str]()
    return {
        "fromVersion": live.version if live else None,
        "textBefore": text_of(live.content) if live else "",
        "textAfter": text_of(v.content),
        "hints": [
            {"line": w["position"]["index"], "message": w["message"]}
            for w in warnings
            if w["kind"] == "hint" and w["position"] is not None
        ],
        "toolsAdded": [t for t in tool_ids(after) if t not in had_tools],
        "kbsAdded": [k for k in after["knowledgeBases"] if k not in had_bases],
    }


async def review_body(rt: Runtime, req: PublishRequestRow) -> Json:
    """A skill publish request as the console's `skillPublish`: the record kept when it opened, with the skill's
    owning team and the agents that pin the skill now."""
    body, row = req.body, await skills(rt).row(req.subject_id)
    v = await skills(rt).version(req.subject_id, int(req.version))
    users = await pinning_agents(rt.db, req.subject_id)
    return {
        "skillId": req.subject_id,
        "skillName": body["skillName"],
        "ownerTeam": row.owner_team,
        "fromVersion": body.get("fromVersion"),
        "toVersion": int(req.version),
        "editClass": "re_test",
        "requestedBy": str(req.requested_by),
        "note": req.note,
        "changes": body.get("changes", []),
        "testRun": None,
        "failing": [],
        "toolsAdded": body.get("toolsAdded", []),
        "kbsAdded": body.get("kbsAdded", []),
        "guardrails": list(content_of(v.content).get("guardrails") or []) if v else [],
        "agents": [{"name": a.spec["name"], "pinnedVersion": a.pinned_version} for a in users],
        "approvalsNeeded": 1,
        # Absent on a request opened before the text was kept with it.
        **({"textBefore": body["textBefore"], "textAfter": body["textAfter"]} if "textAfter" in body else {}),
        "hints": body.get("hints", []),
    }


def snapshot(skill_id: str, version: int, content: SkillContent, tokens: int, *, by: str, at: str) -> SkillPin:
    """What an agent version keeps of a pinned skill version: enough to serve it with no lookup."""
    return cast(
        SkillPin,
        {
            "skillId": skill_id,
            "version": version,
            "name": content["name"],
            "slug": content["slug"],
            "useWhen": content["useWhen"],
            "loading": content["loading"],
            "instructions": content["instructions"],
            "guardrails": content["guardrails"],
            **({"refusal": content.get("refusal")} if content.get("refusal") else {}),
            "toolIds": tool_ids(content),
            "knowledgeBases": content["knowledgeBases"],
            "tokens": tokens,
            **({"parts": content.get("parts")} if content.get("parts") else {}),
            # What it needs to start, so a turn refuses to start it while a required input is missing.
            **({"inputs": content.get("inputs")} if content.get("inputs") else {}),
            # A skill with steps is pinned with them, so the runtime serves the program with no lookup.
            **{k: v for k in skill_content.KEYS if (v := cast(Json, content).get(k))},
            # Written as text: held to the text's publish rule, not the step list's (skill_content.unrunnable).
            **({"fromText": True} if content.get("source") is not None else {}),
            "attachedBy": by,
            "attachedAt": at,
        },
    )


async def pin(
    rt: Runtime, agent_spec: AgentSpec, skill_id: str, version: int, *, by: str, at: str, fresh: bool = True
) -> list[SkillPin]:
    """The agent's pins with `skill_id` attached at `version`, or moved to it. Refused (422) unless the version is
    published, the skill is not deprecated, the agent holds every tool and knowledge base it names, and the agent
    stays within 12 skills."""
    reg = skills(rt)
    row = await reg.find(skill_id)
    if row is None:
        raise NotFound(f"Skill {skill_id}")
    v = await reg.version(skill_id, version)
    if v is None or v.published_at is None:
        raise Unprocessable(
            f"{skill_id} v{version} is not published; only published versions can be attached.", code="not_published"
        )
    if row.deprecated_reason:
        raise Unprocessable(f"{v.content['name']} is deprecated and takes no new attaches.", code="skill_deprecated")
    # A version published before a check existed, or whose tool has since become one that changes something, is held
    # to the checks a save makes now.
    program = skill_content.program_of(v.content)
    runs = program is not None and bool(program.targets())
    # An unreachable tools directory fails the attach as it fails a save, rather than reading every tool as a write.
    access = {str(t["id"]): str(t["access"]) for t in await known_tools(rt, fresh=fresh)} if runs else {}
    text = v.content.get("source") is not None
    if program is not None and (broken := skill_content.unrunnable(program, access, text=text)[0]):
        raise Unprocessable(
            f"{v.content['name']} v{version} cannot be attached as it is: {broken[0]['message']} Fix the skill and "
            "publish it again.",
            code="skill_needs_fix",
            details={"problems": cast(JsonList, broken)},
        )
    if missing := missing_for(content_of(v.content), agent_spec):
        raise Unprocessable(
            f"The agent does not hold {', '.join(missing)}, which {v.content['name']} v{version} names.",
            code="agent_lacks",
            details={"missing": missing},
        )
    pins = [p for p in agent_spec.get("skillPins") or [] if p["skillId"] != skill_id]
    # A skill whose steps run other skills needs each of them attached too: the runtime starts a sub-skill from the
    # agent's own pins.
    held = {str(p["skillId"]) for p in pins}
    if lacking := sorted(skill_content.runs_of(v.content) - held):
        raise Unprocessable(
            f"{v.content['name']} runs {', '.join(lacking)} as a step; attach {'it' if len(lacking) == 1 else 'them'} "
            "to the agent first.",
            code="agent_lacks_skill",
            details={"skills": lacking},
        )
    if len(pins) >= MAX_ATTACHED:
        raise Unprocessable(f"An agent holds at most {MAX_ATTACHED} skills.", code="too_many_skills")
    if v.content["loading"] == "always":
        always = sum(int(p["tokens"]) for p in pins if p["loading"] == "always") + v.tokens
        if always > ALWAYS_BUDGET:
            raise Unprocessable(
                f"Always-on skills on this agent would be {always:,} tokens; the limit is {ALWAYS_BUDGET:,}.",
                code="always_budget",
            )
    return [*pins, snapshot(skill_id, version, content_of(v.content), v.tokens, by=by, at=at)]


async def pin_problems(rt: Runtime, agent_spec: Json) -> list[Problem]:
    """What in an agent version's pinned skills stops its publish (`skill_content.pin_problems`), read against the
    tools directory as it is now."""
    pins = cast(list[Json], agent_spec.get("skillPins") or [])
    if not any(p.get("steps") for p in pins):
        return []
    return skill_content.pin_problems(pins, (await _directory(rt, fresh=True))[0])


def check_pins_hold(agent_spec: AgentSpec) -> None:
    """An agent edit that drops a tool or knowledge base a pinned skill names is refused, so a pin never names scope
    the agent lacks."""
    for p in agent_spec.get("skillPins") or []:
        named = list(p.get("toolIds") or [])
        bases = p.get("knowledgeBases") or []
        tools = set(agent_spec.get("toolIds") or [])
        kbs = set(agent_spec.get("collections") or [])
        if missing := [t for t in (str(t) for t in named) if t not in tools] + [k for k in list(bases) if k not in kbs]:
            raise Unprocessable(
                f"{p['name']} v{p['version']} needs {', '.join(missing)}; detach it before removing them.",
                code="skill_needs_scope",
                details={"missing": missing},
            )


class PinnedSkill(TypedDict):
    skillId: str
    name: str
    useWhen: str
    loading: str
    pinnedVersion: int
    latestPublished: int | None
    status: str
    upgradeAvailable: bool
    upgradeBlocked: NotRequired[str]
    loads7d: int
    share7d: int
    tokens: int


class AvailableSkill(TypedDict):
    skillId: str
    name: str
    useWhen: str
    loading: str
    latestPublished: int | None
    ownerTeam: str
    attachable: bool
    missing: list[str]


class AgentSkillsView(TypedDict):
    agentId: str
    pins: list[PinnedSkill]
    available: list[AvailableSkill]
    limits: dict[str, int]


async def agent_skills(rt: Runtime, agent_id: str) -> AgentSkillsView:
    """The agent page's read model: the newest version's pins, and published skills with whether each attaches."""
    reg, agents = skills(rt), agent_registry(rt)
    arow = await agents.row(agent_id)
    spec = cast(AgentSpec, (await agents.version(agent_id, arow.version)).spec)
    pins = spec.get("skillPins") or []
    rows = {r.id: r for r in await reg.rows()}
    out_pins: list[PinnedSkill] = []
    for p in pins:
        row = rows.get(p["skillId"])
        latest = row.published_version if row else None
        newer = await reg.version(p["skillId"], latest) if row and latest and latest > p["version"] else None
        blocked = missing_for(content_of(newer.content), spec) if newer else []
        out_pins.append(
            cast(
                PinnedSkill,
                {
                    "skillId": p["skillId"],
                    "name": p["name"],
                    "useWhen": p["useWhen"],
                    "loading": p["loading"],
                    "pinnedVersion": p["version"],
                    "latestPublished": latest,
                    "status": _status(row, None) if row else "deprecated",
                    "upgradeAvailable": newer is not None,
                    **(
                        {"upgradeBlocked": f"Needs {', '.join(blocked)}, which the agent does not hold."}
                        if blocked
                        else {}
                    ),
                    "loads7d": 0,
                    "share7d": 0,
                    "tokens": p["tokens"],
                },
            )
        )
    held = {p["skillId"] for p in pins}
    available: list[AvailableSkill] = []
    for row in rows.values():
        if row.id in held or row.published_version is None or row.deprecated_reason:
            continue
        v = await reg.version(row.id, row.published_version)
        assert v is not None
        content = content_of(v.content)
        missing = missing_for(content, spec)
        available.append(
            {
                "skillId": row.id,
                "name": content["name"],
                "useWhen": content["useWhen"],
                "loading": content["loading"],
                "latestPublished": row.published_version,
                "ownerTeam": row.owner_team,
                "attachable": not missing,
                "missing": missing,
            }
        )
    return {"agentId": agent_id, "pins": out_pins, "available": available, "limits": LIMITS}


async def load_seed(rt: Runtime, path: Path) -> None:
    """Seeds each skill in `path` with no row yet, published at v1, and attaches it to the agents it names
    (`seed_agent_version`: published in dev, reviewed elsewhere, never over a person's draft). An existing skill is
    left as it is, so console edits survive a restart."""
    if not path.is_file():  # noqa: ASYNC240
        return
    reg = skills(rt)
    seeds = cast(list[Json], json.loads(path.read_text()))  # noqa: ASYNC240
    for s in seeds:
        if await reg.find(cast(str, s["id"])) is not None:
            continue
        if s.get("toolIds"):
            raise ValueError(f"Seed skill {s['id']} names tools; the start-up seed has no tenant to read them.")
        content = await check_content(rt, s)
        await reg.create(
            content,
            owner_team=cast(str, s["ownerTeam"]),
            team_id=SEED_TEAM,
            origin="blank",
            by="seed",
            skill_id=cast(str, s["id"]),
            published=True,
        )
        v = await reg.version(cast(str, s["id"]), 1)
        assert v is not None
        for aid in cast(list[str], s.get("pinnedBy") or []):

            async def attach(spec: Json, sid: str = cast(str, s["id"]), at: str = v.saved_at) -> Json:
                spec["skillPins"] = cast(
                    JsonValue, await pin(rt, cast(AgentSpec, spec), sid, 1, by=SEED_BY, at=at, fresh=False)
                )
                return spec

            try:
                await seed_agent_version(rt, aid, attach, f"Attached {content['name']} v1")
            except Unprocessable as e:
                # The agent lacks what the skill names: the skill stays published and unattached, and start goes on.
                log.warning("seed_skill_not_attached", skill=s["id"], agent=aid, reason=e.message)


def seed_path(seed_dir: Path, agents_seed_file: Path | None) -> Path:
    """skills.json beside the agents seed, as guardrails.json is."""
    return (agents_seed_file.parent if agents_seed_file else seed_dir) / "skills.json"


def require_unpinned(pinning: list[str], name: str) -> None:
    if pinning:
        raise Conflict(f"{name} is attached to {', '.join(pinning)}; detach it first.", code="skill_pinned")


async def usable(rt: Runtime, *, team: str, menu: str, pinned: list[str]) -> list[tuple[SkillRow, SkillVersionRow]]:
    """(skill row, published version) of each skill of `team` a chat with an agent may use under its skill menu
    setting: every published, live one for the `team` menu, the agent's own for `attached`, none for `off`. Only the
    conversation's team counts, whatever team the request reads as (a dev caller reads every team)."""
    if menu == "off":
        return []
    return await skills(rt).published_in(team, pinned if menu == "attached" else None)


PICKED = "Picked from the / menu"


def _picked(entry: Json) -> bool:
    """A skill the person chose from the / menu on this or an earlier reply (a carried entry keeps its `matched`)."""
    return entry.get("matched") == PICKED or bool(entry.get("inputs"))


def _offered(menu: str, skill_id: str, pinned: list[str]) -> bool:
    """Whether an agent's skill menu setting offers the skill in its / menu."""
    return menu == "team" or (menu == "attached" and skill_id in pinned)


def _key(entry: Json) -> tuple[str, str]:
    return str(entry.get("skillId")), str(entry.get("part") or "")


async def _rendered(rt: Runtime, team: str, skill_id: str, part: str | None, given: dict[str, str]) -> KernelSkill:
    """The published skill of `team`, or one part of it, as the kernel loads it, with the inputs filled in."""
    out = await render_published(rt, skill_id, part, given, team=team)
    v = await skills(rt).version(skill_id, int(out["version"]))
    assert v is not None
    entry = next(
        s
        for s in kernel_skills(skill_id, int(out["version"]), str(out["slug"]), v.content)
        if s.part == (out.get("part") or "")
    )
    return replace(entry, instructions=str(out["text"]), tokens=max(1, (len(str(out["text"])) + 3) // 4))


async def skill_turn(
    rt: Runtime,
    agent: AgentDefinition,
    pick: SkillPick | None,
    earlier: list[Json],
    *,
    team: str,
    may_pick: bool = True,
) -> SkillTurn | None:
    """The skills one chat reply runs with beyond the agent's pins: the team's published skills its menu setting
    allows (offered to load on a match), the skills the reply before carried, and the part the person picked, filled
    with its inputs. `team` is the conversation's: no skill of another team is offered or loaded. None when there are
    none, so a reply without skills runs as before. A part picked earlier is carried only while `may_pick` (the
    person still holds skills: view) and the agent's menu still offers it.

    Raises:
        Unprocessable: `skill_menu_limit` when the agent's setting does not offer the pick, `skill_needs_scope` when
            the skill names a tool or knowledge base the agent lacks, `skill_budget` past the reply's caps, and
            `render_published`'s codes (`skill_not_published`, `missing_input`, ...).
    """
    pinned = [k.skill_id for k in agent.skills]
    holds: SkillHolds = {"toolIds": list(agent.tools), "collections": list(agent.default_kb_ids)}
    extra: list[KernelSkill] = []
    if agent.skill_menu == "team":
        for r, v in await usable(rt, team=team, menu="team", pinned=pinned):
            if r.id in pinned or v.content.get("loading") != "on_match" or missing_for(content_of(v.content), holds):
                continue
            extra.extend(kernel_skills(r.id, v.version, r.slug, v.content, v.tokens))
    # The reply before's on-match skills stay loaded; always-on ones load again from the pins.
    carried: list[Json] = [
        {**e, "how": "carried"} for e in earlier if e.get("how") != "always" and e.get("matched") != "Always on"
    ]
    carried = [
        e for e in carried if not _picked(e) or (may_pick and _offered(agent.skill_menu, str(e.get("skillId")), pinned))
    ]
    if pick is not None:
        if not _offered(agent.skill_menu, pick.skill_id, pinned):
            raise Unprocessable(
                f"{agent.name} does not offer that skill in chat; ask an admin to change its skill menu setting.",
                code="skill_menu_limit",
            )
        picked = await _rendered(rt, team, pick.skill_id, pick.part, pick.inputs)
        v = await skills(rt).version(pick.skill_id, picked.version)
        if missing := missing_for(content_of(v.content if v is not None else {}), holds):
            raise Unprocessable(
                f"{picked.name} needs {', '.join(missing)}, which {agent.name} does not have; grant it on the agent "
                "first.",
                code="skill_needs_scope",
                details={"needs": missing},
            )
        key = (picked.skill_id, picked.part)
        carried = [e for e in carried if _key(e) != key]
        if len({_key(e) for e in carried}) + 1 > MAX_PER_TURN:
            raise Unprocessable(
                f"At most {MAX_PER_TURN} skills run in one reply, and this conversation already carries "
                f"{len(carried)}; start a new chat to use {picked.name}.",
                code="skill_budget",
            )
        limit = min(picked.budget or TOKEN_BUDGET, TOKEN_BUDGET)
        if picked.tokens > limit:
            raise Unprocessable(
                f"{picked.name} filled in is {picked.tokens:,} tokens, over its {limit:,}-token budget; shorten the "
                "inputs.",
                code="skill_budget",
            )
        extra.insert(0, picked)
        entry: Json = {"skillId": picked.skill_id, "version": picked.version}
        if picked.part:
            entry["part"] = picked.part
        entry["matched"], entry["how"] = PICKED, "picked"
        if pick.inputs:
            entry["inputs"] = cast(JsonValue, pick.inputs)
        carried.append(entry)
    # A carried pick of a team skill keeps the text its inputs filled.
    for e in carried:
        if e.get("how") == "carried" and e.get("inputs") and e["skillId"] not in pinned:
            try:
                extra.insert(
                    0,
                    await _rendered(
                        rt, team, str(e["skillId"]), cast(str | None, e.get("part")), cast(dict[str, str], e["inputs"])
                    ),
                )
            except (NotFound, Unprocessable):
                continue
    # With an earlier reply, the turn's carried list replaces the history's, so a dropped pick does not come back.
    if not extra and not carried and not earlier:
        return None
    seen: set[tuple[str, str]] = set()
    unique = [s for s in extra if (s.skill_id, s.part) not in seen and not seen.add((s.skill_id, s.part))]
    return {"skills": [_wired(s) for s in unique], "carried": carried}


def _wired(skill: KernelSkill) -> dict[str, JsonValue]:
    """A kernel skill as JSON for the graph's state; `agent_wrapper` reads the program back into its model."""
    program = skill.program.model_dump(mode="json", by_alias=True) if skill.program is not None else None
    return {**asdict(replace(skill, program=None)), "program": program}


class SkillTurn(TypedDict):
    """The skills one chat reply runs with (kernel skills, as dicts) and the entries the next reply carries."""

    skills: list[dict[str, JsonValue]]
    carried: list[Json]
