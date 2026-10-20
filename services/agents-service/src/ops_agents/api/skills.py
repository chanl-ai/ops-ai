"""Skills as versioned attachments (spec 11, c-063 slice 2): the views the console's skills pages and agent page
read, the checks on a skill's content, the publish an approval runs, and the pin check an attach runs.

An agent version snapshots each pinned skill version (`skillPins[]`: id, version, name, slug, useWhen, loading,
instructions, guardrails, tokens, toolIds, knowledgeBases), so the runtime serves the pin with no lookup per turn.
Not built yet (spec 11 sections 4.4, 4.5, 5.6, 5.7): skill tests, load counts, generation, import and export; the
views return those as empty and the docs page says so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ops_service_kit.errors import Conflict, NotFound, Unprocessable, ValidationFailed
from ops_service_kit.logging import get_logger

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
    if unknown := [t for t in tool_ids if t not in offered]:
        raise ValidationFailed(f"Unknown tools: {', '.join(unknown)}.", code="unknown_tool")
    return {
        "name": name,
        "slug": str(fields.get("slug") or slug_of(name)),
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
    }


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
    rt: Runtime, row: dict[str, Any], pins: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]
) -> dict[str, Any]:
    reg = skills(rt)
    newest = await reg.version(row["id"], int(row["version"]))
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
        "draftVersion": row["version"] if newest["published_at"] is None else None,
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
        **({"pendingReviewId": pending["id"]} if pending else {}),
    }


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
    budget = TOKEN_BUDGET if newest["content"]["loading"] == "on_match" else ALWAYS_BUDGET
    if newest["tokens"] > budget:
        blockers.append(
            f"v{newest['version']} is {newest['tokens']:,} tokens; a {newest['content']['loading']} body over "
            f"{budget:,} could never load. Shorten it."
        )
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
