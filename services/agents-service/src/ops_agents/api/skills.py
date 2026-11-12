"""Skills as versioned attachments (spec 11): the views the console's skills pages and agent page
read, the checks on a skill's content, the publish an approval runs, and the pin check an attach runs.

An agent version snapshots each pinned skill version (`skillPins[]`: id, version, name, slug, useWhen, loading,
instructions, guardrails, tokens, toolIds, knowledgeBases), so the runtime serves the pin with no lookup per turn.
Not built yet (spec 11 sections 4.4, 4.5, 5.6, 5.7): skill tests, load counts, generation, import and export; the
views return those as empty and the docs page says so.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

from ops_agent_kernel.types import Skill as KernelSkill
from ops_contracts.chat import SkillPick
from ops_service_kit.errors import Conflict, NotFound, Unprocessable, ValidationFailed
from ops_service_kit.logging import get_logger

from ..activities.catalog import AgentDefinition, kernel_skills
from ..store.skills import SkillRegistry, slug_of
from .agent_registry import SEED_BY, SEED_TEAM, seed_agent_version
from .agent_registry import registry as agent_registry
from .child_runs import published_workflows
from .deps import Runtime
from .routers.tool_catalog import known_tools

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


def skills(rt: Runtime) -> SkillRegistry:
    return SkillRegistry(rt.db)


async def check_content(rt: Runtime, fields: dict[str, Any]) -> dict[str, Any]:
    """A version's content, normalised; refused when the model could never choose it or it names a tool the directory
    does not offer. The tools are kept as references with the directory's names and access."""
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
    if not str(fields.get("instructions") or "").strip():
        raise ValidationFailed("Write the skill's instructions.", code="no_instructions")
    tool_ids = list(dict.fromkeys(str(t) for t in cast(list[Any], fields.get("toolIds") or [])))
    # The directory is read per tenant, so a skill naming no tool does not need it (the start-up seed has no tenant).
    offered = {t["id"]: t for t in await known_tools(rt)} if tool_ids else {}
    if any(t not in offered for t in tool_ids):
        # A tool offered moments ago is not in the list kept for 30 s: ask once more before refusing it.
        offered = {t["id"]: t for t in await known_tools(rt, fresh=True)}
    if unknown := [t for t in tool_ids if t not in offered]:
        raise ValidationFailed(f"Unknown tools: {', '.join(unknown)}.", code="unknown_tool")
    slug = str(fields.get("slug") or slug_of(name))
    parts = _parts(fields.get("parts"), tool_ids, loading)
    if parts:
        await _check_overview(rt, fields, slug, parts)
    return {
        "name": name,
        "slug": slug,
        "useWhen": use_when,
        "loading": loading,
        "instructions": str(fields["instructions"]).strip(),
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
        "knowledgeBases": list(dict.fromkeys(str(k) for k in cast(list[Any], fields.get("knowledgeBases") or []))),
        "guardrails": [g for g in (str(x).strip() for x in cast(list[Any], fields.get("guardrails") or [])) if g],
        "resources": [],
        # Kept only when written, so a version saved before the field keeps its digest.
        **({"refusal": refusal} if (refusal := str(fields.get("refusal") or "").strip()) else {}),
        **({"inputs": inputs} if (inputs := _inputs(fields.get("inputs"))) else {}),
        **({"parts": parts} if parts else {}),
    }


def _parts(raw: Any, tool_ids: list[str], loading: str) -> list[dict[str, Any]]:
    """The skill's named parts, each read with the shared instructions; a version saved without any keeps no key, so
    its digest is unchanged. A part's tools are some of the skill's own, so picking a part never adds scope."""
    parts: list[dict[str, Any]] = []
    for f in cast(list[dict[str, Any]], raw or []):
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
        part_tools = list(dict.fromkeys(str(t) for t in cast(list[Any], f.get("toolIds") or [])))
        if outside := [t for t in part_tools if t not in tool_ids]:
            raise ValidationFailed(
                f"Part {name} names {', '.join(outside)}, which the skill does not; add it to the skill's tools.",
                code="part_tool_not_in_skill",
            )
        budget = int(f.get("budget") or 0)
        if budget and not 0 < budget <= TOKEN_BUDGET:
            raise ValidationFailed(f"A part's budget is 1 to {TOKEN_BUDGET:,} tokens.", code="bad_part_budget")
        if budget and (len(instructions) + 3) // 4 > budget:
            raise ValidationFailed(
                f"Part {name} is longer than its own {budget:,}-token budget; shorten it or raise the budget.",
                code="part_over_budget",
            )
        parts.append(
            {
                "slug": slug,
                "name": name,
                "useWhen": use_when,
                "instructions": instructions,
                **({"inputs": inputs} if (inputs := _inputs(f.get("inputs"))) else {}),
                **({"toolIds": part_tools} if part_tools else {}),
                **({"budget": budget} if budget else {}),
            }
        )
    if len(parts) > MAX_PARTS:
        raise ValidationFailed(f"A skill has at most {MAX_PARTS} parts.", code="too_many_parts")
    return parts


async def _check_overview(rt: Runtime, fields: dict[str, Any], slug: str, parts: list[dict[str, Any]]) -> None:
    """A skill with parts: the shared text stays short, inputs sit on the parts, and no part's assistant prompt name
    (`<skill>-<part>`) is another skill's name."""
    if len(str(fields.get("instructions") or "").strip()) > OVERVIEW_MAX:
        raise ValidationFailed(
            f"With parts, the shared instructions are at most {OVERVIEW_MAX:,} characters; move the rest into a part.",
            code="overview_too_long",
        )
    if fields.get("inputs"):
        raise ValidationFailed("A skill with parts takes its inputs on each part.", code="inputs_on_parts")
    taken = {str(r["slug"]) for r in await skills(rt).rows()} - {slug}
    if clash := [f"{slug}-{p['slug']}" for p in parts if f"{slug}-{p['slug']}" in taken]:
        raise ValidationFailed(
            f"{', '.join(clash)} is already another skill's name; rename the part.", code="part_name_taken"
        )


def render(content: dict[str, Any], part: str | None, given: dict[str, str]) -> dict[str, Any]:
    """The text a person or assistant uses: the skill's instructions, or its shared instructions and one part, with
    the inputs filled in. The one place inputs become text; chat and the MCP prompts both call it.

    Raises:
        Unprocessable: `part_required` or `unknown_part` for the part, `unknown_input` for a value the skill does
            not ask for, `missing_input` naming each required input left empty.
    """
    name = str(content["name"])
    parts = cast(list[dict[str, Any]], content.get("parts") or [])
    chosen = next((p for p in parts if p["slug"] == part), None) if part else None
    slugs = [p["slug"] for p in parts]
    if part and chosen is None:
        raise Unprocessable(f"{name} has no part {part}.", code="unknown_part", details={"parts": slugs})
    if parts and chosen is None:
        raise Unprocessable(
            f"Pick a part of {name}: {', '.join(slugs)}.", code="part_required", details={"parts": slugs}
        )
    declared = cast(list[dict[str, Any]], (chosen or content).get("inputs") or [])
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
    text = str(content["instructions"])
    if chosen is not None:
        text += "\n\n" + str(chosen["instructions"])
    for n, v in values.items():
        # An optional input left empty is dropped, never left as {{name}}.
        text = text.replace("{{" + n + "}}", v)
    if filled := [f"- {n}: {v}" for n, v in values.items() if v]:
        text += "\n\nInputs:\n" + "\n".join(filled)
    return {
        "text": text,
        **({"part": chosen["slug"], "partName": chosen["name"]} if chosen else {}),
    }


async def render_published(rt: Runtime, skill_id: str, part: str | None, given: dict[str, str]) -> dict[str, Any]:
    """`render` on the skill's published version, never a draft.

    Raises:
        NotFound: no such skill in the team.
        Unprocessable: `skill_not_published` when it has no published version or is deprecated; `render`'s codes.
    """
    reg = skills(rt)
    row = await reg.find(skill_id)
    if row is None:
        raise NotFound(f"Skill {skill_id}")
    v = await reg.version(skill_id, int(row["published_version"])) if row["published_version"] else None
    if v is None or row["deprecated_reason"]:
        raise Unprocessable(
            f"{row['slug']} has no published version in use; only a published skill can be used.",
            code="skill_not_published",
        )
    return {
        "skillId": skill_id,
        "name": v["content"]["name"],
        "slug": row["slug"],
        "version": v["version"],
        **render(v["content"], part, given),
    }


def _inputs(raw: Any) -> list[dict[str, Any]]:
    """The skill's inputs, each name once; a version saved without any keeps no key, so its digest is unchanged."""
    out: dict[str, dict[str, Any]] = {}
    for f in cast(list[dict[str, Any]], raw or []):
        name = str(f.get("name") or "").strip()
        if name and name not in out:
            out[name] = {
                "name": name,
                "type": "string",
                "description": str(f.get("description") or "").strip(),
                "required": bool(f.get("required")),
            }
    return list(out.values())


def tool_ids(content: dict[str, Any]) -> list[str]:
    tools: list[dict[str, Any]] = list(content.get("tools") or [])
    return [str(t["toolId"]) for t in tools]


def missing_for(content: dict[str, Any], agent_spec: dict[str, Any]) -> list[str]:
    """Tools and knowledge bases the skill names that the agent does not hold: a skill never adds scope."""
    tools = set(agent_spec.get("toolIds") or [])
    kbs = set(agent_spec.get("collections") or [])
    named: list[str] = list(content.get("knowledgeBases") or [])
    return [t for t in tool_ids(content) if t not in tools] + [k for k in named if k not in kbs]


async def _requests(rt: Runtime, skill_id: str) -> list[dict[str, Any]]:
    return await agent_registry(rt).requests("skill", skill_id)


async def _pinning(rt: Runtime) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """(agent row, agent version spec, pin) for each skill pin on an agent's newest version."""
    reg = agent_registry(rt)
    out: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for row in await reg.rows():
        spec = (await reg.version(row["id"], int(row["version"])))["spec"]
        out.extend((row, spec, p) for p in cast(list[dict[str, Any]], spec.get("skillPins") or []))
    return out


async def pinned_by(rt: Runtime, skill_id: str) -> list[str]:
    """Agents whose newest or published version pins the skill (the published one serves chat), and published
    workflows whose agent steps carry it (a workflow keeps the agent version it was published with)."""
    reg = agent_registry(rt)
    names: set[str] = set()
    for row in await reg.rows():
        for n in {row["version"], row["published_version"]} - {None}:
            spec = (await reg.version(row["id"], int(n)))["spec"]
            pins: list[dict[str, Any]] = list(spec.get("skillPins") or [])
            if any(p["skillId"] == skill_id for p in pins):
                names.add(str(spec["name"]))
    names.update(await workflows_pinning(rt, "skills", "skill_id", skill_id))
    return sorted(names)


async def workflows_pinning(rt: Runtime, field: str, key: str, value: str) -> set[str]:
    """Published workflows with an agent step whose pinned agent carries `value` under `field[].key`."""
    out: set[str] = set()
    if rt.graph_store is None:
        return out
    for row in await published_workflows(rt):
        d = await rt.graph_store.version(row["id"], int(row["published_version"]))
        definition: dict[str, Any] = dict((d or {}).get("definition") or {})
        nodes: list[dict[str, Any]] = list(definition.get("nodes") or [])
        for n in nodes:
            config: dict[str, Any] = dict(n.get("config") or {})
            agent: dict[str, Any] = dict(config.get("agent") or {})
            held: list[dict[str, Any]] = list(agent.get(field) or [])
            if n.get("kind") == "agent_turn" and any(x.get(key) == value for x in held):
                out.add(f"workflow {row['name']}")
    return out


def _status(row: dict[str, Any], pending: dict[str, Any] | None) -> str:
    if row["deprecated_reason"]:
        return "deprecated"
    if pending is not None and pending["version"] == row["version"]:
        return "in_review"
    return "published" if row["published_version"] is not None else "draft"


def _version_state(row: dict[str, Any], v: dict[str, Any], requests: list[dict[str, Any]]) -> str:
    n, pub = v["version"], row["published_version"]
    if v["published_at"] is not None:
        if row["deprecated_reason"]:
            return "deprecated"
        return "published" if n == pub else "superseded"
    mine = [r for r in requests if r["version"] == n]
    if any(r["status"] == "pending" for r in mine):
        return "in_review"
    if any(r["status"] == "rejected" for r in mine):
        return "rejected"
    return "draft"


async def row_view(
    rt: Runtime,
    row: dict[str, Any],
    pins: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    *,
    served: bool = False,
) -> dict[str, Any]:
    """One list row. `served` describes the published version (what chat and the MCP prompts use) instead of the
    newest one an editor sees."""
    reg = skills(rt)
    newest = await reg.version(row["id"], int(row["published_version"] if served else row["version"]))
    assert newest is not None
    requests = await _requests(rt, row["id"])
    pending = next((r for r in requests if r["status"] == "pending"), None)
    content = newest["content"]
    users = [(a, s) for a, s, p in pins if p["skillId"] == row["id"]]
    return {
        "id": row["id"],
        "name": content["name"],
        "slug": row["slug"],
        "useWhen": content["useWhen"],
        "loading": content["loading"],
        "ownerTeam": row["owner_team"],
        "status": _status(row, pending),
        "version": row["version"],
        "publishedVersion": row["published_version"],
        "draftVersion": row["version"] if row["version"] != row["published_version"] else None,
        "usedBy": len(users),
        "liveAgents": sum(1 for a, _ in users if a["published_version"] is not None and not a["paused"]),
        "toolCount": len(content["tools"]),
        "kbCount": len(content["knowledgeBases"]),
        # Skill tests are not built yet (spec 11 4.4), so there is no pass rate to report.
        "lastEvalPassRate": None,
        "tokens": newest["tokens"],
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
        "origin": row["origin"],
        "inputs": content.get("inputs") or [],
        "parts": [
            {"slug": p["slug"], "name": p["name"], "useWhen": p["useWhen"], "inputs": p.get("inputs") or []}
            for p in cast(list[dict[str, Any]], content.get("parts") or [])
        ],
        **({"pendingReviewId": pending["id"]} if pending else {}),
    }


def over_budget(v: dict[str, Any]) -> str | None:
    """Why a version could never load because of its size, or None: an on-match body (with parts, the shared text and
    its longest part) past the reply's skill budget, an always-on body past the always-on budget."""
    budget = TOKEN_BUDGET if v["content"]["loading"] == "on_match" else ALWAYS_BUDGET
    if v["tokens"] <= budget:
        return None
    return (
        f"v{v['version']} is {v['tokens']:,} tokens; a {v['content']['loading']} body over {budget:,} could never "
        "load. Shorten it."
    )


async def detail(rt: Runtime, skill_id: str) -> dict[str, Any]:
    reg = skills(rt)
    row = await reg.row(skill_id)
    pins = await _pinning(rt)
    base = await row_view(rt, row, pins)
    versions = await reg.versions(skill_id)
    requests = await _requests(rt, skill_id)
    pending = next((r for r in requests if r["status"] == "pending"), None)
    newest = versions[0]
    blockers: list[str] = []
    if row["deprecated_reason"]:
        blockers.append("The skill is deprecated.")
    elif newest["published_at"] is not None:
        blockers.append(f"v{newest['version']} is already published; save a change to open a draft.")
    elif pending is not None:
        blockers.append(f"{pending['id']} is already open for v{pending['version']}.")
    if too_long := over_budget(newest):
        blockers.append(too_long)
    latest = row["published_version"]
    usage: list[dict[str, Any]] = []
    for a, spec, p in pins:
        if p["skillId"] != skill_id:
            continue
        newer = await reg.version(skill_id, int(latest)) if latest and latest > p["version"] else None
        blocked = missing_for(newer["content"], spec) if newer else []
        usage.append(
            {
                "agentId": a["id"],
                "agentName": spec["name"],
                "agentTeamId": a["team_id"],
                "agentAvailability": "paused"
                if a["paused"]
                else "published"
                if a["published_version"] is not None
                else "not_published",
                "pinnedVersion": p["version"],
                "latestPublished": latest,
                "upgradeAvailable": newer is not None,
                **(
                    {"upgradeBlocked": f"Needs {', '.join(blocked)}, which the agent does not hold."} if blocked else {}
                ),
                # Loads are not counted per agent yet.
                "loads7d": 0,
                "share7d": 0,
                "lastLoadedAt": None,
                "attachedAt": p.get("attachedAt") or a["updated_at"],
                "attachedBy": p.get("attachedBy") or "",
            }
        )
    return {
        **base,
        "content": newest["content"],
        "versions": [
            {
                "version": v["version"],
                "state": _version_state(row, v, requests),
                "editClass": "re_test",
                "note": v["note"],
                "changes": v["changes"],
                "savedBy": v["saved_by"],
                "savedAt": v["saved_at"],
                "content": v["content"],
                "tokens": v["tokens"],
                **({"reviewId": v["review_id"]} if v["review_id"] else {}),
                **({"publishedAt": v["published_at"], "publishedBy": v["published_by"]} if v["published_at"] else {}),
                "testRun": None,
            }
            for v in versions
        ],
        "tests": [],
        "runs": [],
        "usage": usage,
        "activity": {"agents": [], "loadsPerDay": [], "loads30d": 0, "successRate": None, "samples": []},
        "provenance": {"origin": row["origin"], "detail": "", "citations": []},
        **(
            {
                "pendingReview": {
                    "id": pending["id"],
                    "version": pending["version"],
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
            "editClass": "re_test",
            "approversNeeded": 1,
        },
    }


async def publish(rt: Runtime, req: dict[str, Any], by: str) -> None:
    await skills(rt).publish(req["subject_id"], int(req["version"]), by=by, review_id=req["id"])


def snapshot(skill_id: str, version: int, content: dict[str, Any], tokens: int, *, by: str, at: str) -> dict[str, Any]:
    """What an agent version keeps of a pinned skill version: enough to serve it with no lookup."""
    return {
        "skillId": skill_id,
        "version": version,
        "name": content["name"],
        "slug": content["slug"],
        "useWhen": content["useWhen"],
        "loading": content["loading"],
        "instructions": content["instructions"],
        "guardrails": content["guardrails"],
        **({"refusal": content["refusal"]} if content.get("refusal") else {}),
        "toolIds": tool_ids(content),
        "knowledgeBases": content["knowledgeBases"],
        "tokens": tokens,
        **({"parts": content["parts"]} if content.get("parts") else {}),
        "attachedBy": by,
        "attachedAt": at,
    }


async def pin(
    rt: Runtime, agent_spec: dict[str, Any], skill_id: str, version: int, *, by: str, at: str
) -> list[dict[str, Any]]:
    """The agent's pins with `skill_id` attached at `version`, or moved to it. Refused (422) unless the version is
    published, the skill is not deprecated, the agent holds every tool and knowledge base it names, and the agent
    stays within 12 skills."""
    reg = skills(rt)
    row = await reg.find(skill_id)
    if row is None:
        raise NotFound(f"Skill {skill_id}")
    v = await reg.version(skill_id, version)
    if v is None or v["published_at"] is None:
        raise Unprocessable(
            f"{skill_id} v{version} is not published; only published versions can be attached.", code="not_published"
        )
    if row["deprecated_reason"]:
        raise Unprocessable(f"{v['content']['name']} is deprecated and takes no new attaches.", code="skill_deprecated")
    if missing := missing_for(v["content"], agent_spec):
        raise Unprocessable(
            f"The agent does not hold {', '.join(missing)}, which {v['content']['name']} v{version} names.",
            code="agent_lacks",
            details={"missing": missing},
        )
    pins = [p for p in cast(list[dict[str, Any]], agent_spec.get("skillPins") or []) if p["skillId"] != skill_id]
    if len(pins) >= MAX_ATTACHED:
        raise Unprocessable(f"An agent holds at most {MAX_ATTACHED} skills.", code="too_many_skills")
    if v["content"]["loading"] == "always":
        always = sum(int(p["tokens"]) for p in pins if p["loading"] == "always") + int(v["tokens"])
        if always > ALWAYS_BUDGET:
            raise Unprocessable(
                f"Always-on skills on this agent would be {always:,} tokens; the limit is {ALWAYS_BUDGET:,}.",
                code="always_budget",
            )
    return [*pins, snapshot(skill_id, version, v["content"], v["tokens"], by=by, at=at)]


def check_pins_hold(agent_spec: dict[str, Any]) -> None:
    """An agent edit that drops a tool or knowledge base a pinned skill names is refused, so a pin never names scope
    the agent lacks."""
    for p in cast(list[dict[str, Any]], agent_spec.get("skillPins") or []):
        named: list[str] = list(p.get("toolIds") or [])
        content: dict[str, Any] = {
            "tools": [{"toolId": t} for t in named],
            "knowledgeBases": p.get("knowledgeBases") or [],
        }
        if missing := missing_for(content, agent_spec):
            raise Unprocessable(
                f"{p['name']} v{p['version']} needs {', '.join(missing)}; detach it before removing them.",
                code="skill_needs_scope",
                details={"missing": missing},
            )


async def agent_skills(rt: Runtime, agent_id: str) -> dict[str, Any]:
    """The agent page's read model: the newest version's pins, and published skills with whether each attaches."""
    reg, agents = skills(rt), agent_registry(rt)
    arow = await agents.row(agent_id)
    spec = (await agents.version(agent_id, int(arow["version"])))["spec"]
    pins = cast(list[dict[str, Any]], spec.get("skillPins") or [])
    rows = {r["id"]: r for r in await reg.rows()}
    out_pins: list[dict[str, Any]] = []
    for p in pins:
        row = rows.get(p["skillId"])
        latest = row["published_version"] if row else None
        newer = await reg.version(p["skillId"], int(latest)) if row and latest and latest > p["version"] else None
        blocked = missing_for(newer["content"], spec) if newer else []
        out_pins.append(
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
                    {"upgradeBlocked": f"Needs {', '.join(blocked)}, which the agent does not hold."} if blocked else {}
                ),
                "loads7d": 0,
                "share7d": 0,
                "tokens": p["tokens"],
            }
        )
    held = {p["skillId"] for p in pins}
    available: list[dict[str, Any]] = []
    for row in rows.values():
        if row["id"] in held or row["published_version"] is None or row["deprecated_reason"]:
            continue
        v = await reg.version(row["id"], int(row["published_version"]))
        assert v is not None
        missing = missing_for(v["content"], spec)
        available.append(
            {
                "skillId": row["id"],
                "name": v["content"]["name"],
                "useWhen": v["content"]["useWhen"],
                "loading": v["content"]["loading"],
                "latestPublished": row["published_version"],
                "ownerTeam": row["owner_team"],
                "attachable": not missing,
                "missing": missing,
            }
        )
    return {"agentId": agent_id, "pins": out_pins, "available": available, "limits": LIMITS}


async def load_seed(rt: Runtime, path: Path) -> None:
    """Seeds each skill in `path` with no row yet, published at v1, and attaches it to the agents it names
    (`seed_agent_version`: published in dev, reviewed elsewhere, never over a person's draft). An existing skill is
    left as it is, so console edits survive a restart."""
    if not path.is_file():
        return
    reg = skills(rt)
    seeds: list[dict[str, Any]] = json.loads(path.read_text())
    for s in seeds:
        if await reg.find(s["id"]) is not None:
            continue
        if s.get("toolIds"):
            raise ValueError(f"Seed skill {s['id']} names tools; the start-up seed has no tenant to read them.")
        content = await check_content(rt, s)
        await reg.create(
            content,
            owner_team=s["ownerTeam"],
            team_id=SEED_TEAM,
            origin="blank",
            by="seed",
            skill_id=s["id"],
            published=True,
        )
        v = await reg.version(s["id"], 1)
        assert v is not None
        for aid in cast(list[str], s.get("pinnedBy") or []):

            async def attach(spec: dict[str, Any], sid: str = s["id"], at: str = v["saved_at"]) -> dict[str, Any]:
                spec["skillPins"] = await pin(rt, spec, sid, 1, by=SEED_BY, at=at)
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


async def usable(rt: Runtime, *, menu: str, pinned: list[str]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(skill row, published version) of each skill a chat with an agent may use under its skill menu setting: every
    published, live skill for `team`, the agent's own for `attached`, none for `off`."""
    if menu == "off":
        return []
    reg = skills(rt)
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for r in await reg.rows():
        if r["published_version"] is None or r["deprecated_reason"] or (menu == "attached" and r["id"] not in pinned):
            continue
        if (v := await reg.version(r["id"], int(r["published_version"]))) is not None:
            out.append((r, v))
    return out


def _key(entry: dict[str, Any]) -> tuple[str, str]:
    return str(entry.get("skillId")), str(entry.get("part") or "")


async def _rendered(rt: Runtime, skill_id: str, part: str | None, given: dict[str, str]) -> KernelSkill:
    """The published skill, or one part of it, as the kernel loads it, with the inputs filled in."""
    out = await render_published(rt, skill_id, part, given)
    v = await skills(rt).version(skill_id, int(out["version"]))
    assert v is not None
    entry = next(
        s
        for s in kernel_skills(skill_id, int(out["version"]), str(out["slug"]), v["content"])
        if s.part == (out.get("part") or "")
    )
    return replace(entry, instructions=str(out["text"]), tokens=max(1, (len(str(out["text"])) + 3) // 4))


async def skill_turn(
    rt: Runtime, agent: AgentDefinition, pick: SkillPick | None, earlier: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The skills one chat reply runs with beyond the agent's pins: the team's published skills its menu setting
    allows (offered to load on a match), the skills the reply before carried, and the part the person picked, filled
    with its inputs. None when there are none, so a reply without skills runs as before.

    Raises:
        Unprocessable: `skill_menu_limit` when the agent's setting does not offer the pick, `skill_needs_scope` when
            the skill names a tool or knowledge base the agent lacks, `skill_budget` past the reply's caps, and
            `render_published`'s codes (`skill_not_published`, `missing_input`, ...).
    """
    pinned = [k.skill_id for k in agent.skills]
    holds = {"toolIds": list(agent.tools), "collections": list(agent.default_kb_ids)}
    extra: list[KernelSkill] = []
    if agent.skill_menu == "team":
        for r, v in await usable(rt, menu="team", pinned=pinned):
            if r["id"] in pinned or v["content"].get("loading") != "on_match" or missing_for(v["content"], holds):
                continue
            extra.extend(kernel_skills(r["id"], int(v["version"]), str(r["slug"]), v["content"], int(v["tokens"])))
    # The reply before's on-match skills stay loaded; always-on ones load again from the pins.
    carried = [{**e, "how": "carried"} for e in earlier if e.get("how") != "always" and e.get("matched") != "Always on"]
    if pick is not None:
        if agent.skill_menu == "off" or (agent.skill_menu == "attached" and pick.skill_id not in pinned):
            raise Unprocessable(
                f"{agent.name} does not offer that skill in chat; ask an admin to change its skill menu setting.",
                code="skill_menu_limit",
            )
        picked = await _rendered(rt, pick.skill_id, pick.part, pick.inputs)
        v = await skills(rt).version(pick.skill_id, picked.version)
        if missing := missing_for(cast(dict[str, Any], (v or {}).get("content") or {}), holds):
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
        carried.append(
            {
                "skillId": picked.skill_id,
                "version": picked.version,
                **({"part": picked.part} if picked.part else {}),
                "matched": "Picked from the / menu",
                "how": "picked",
                **({"inputs": pick.inputs} if pick.inputs else {}),
            }
        )
    # A carried pick of a team skill keeps the text its inputs filled.
    for e in carried:
        if e.get("how") == "carried" and e.get("inputs") and e["skillId"] not in pinned:
            try:
                extra.insert(0, await _rendered(rt, str(e["skillId"]), e.get("part"), dict(e["inputs"])))
            except (NotFound, Unprocessable):
                continue
    if not extra and not carried:
        return None
    seen: set[tuple[str, str]] = set()
    unique = [s for s in extra if (s.skill_id, s.part) not in seen and not seen.add((s.skill_id, s.part))]
    return {"skills": [asdict(s) for s in unique], "carried": carried}
