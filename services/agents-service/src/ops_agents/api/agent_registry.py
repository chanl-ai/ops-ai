"""The agent registry: agents as rows with immutable versions, a published pointer and publish requests.

Every save is a new version holding the whole spec (instructions, model, tools, knowledge bases, guardrails). The
published pointer names the version the runtime serves: publishing it puts that version's definition in the catalogue,
where chat and the agent graphs read agents, and compiles the agent's own one-node graph, `agent:<id>`. Drafts never
reach the catalogue, so editing an agent changes nothing live until a publish.

Publish requests are shared with workflows (`kind`). Whether one is approved as it is made or waits for a reviewer is
the team's publish policy (api/publish_policy.py).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ops_access import can
from ops_agent_kernel.layout import required_tools
from ops_agents.activities.agent_limits import limits_of
from ops_agents.activities.catalog import AgentDefinition, Catalog, Fragment, GuardrailRule, SkillPinRule, WidgetPinRule
from ops_service_kit.errors import Conflict, NotFound, Unprocessable
from ops_service_kit.logging import get_logger

from ..store.agent_registry import (
    AgentRegistry,
)
from ..store.graphs import GraphStore
from .auth import Principal, caller_of
from .deps import Runtime
from .review_text import requester

# The team that owns every seeded agent and workflow: Operations, under the id platform-service's dev seed gives it, so
# agents-service, tools-service and platform-service name it the same way and no seed carries a placeholder team.
log = get_logger("ops_agents.agent_registry")
SEED_TEAM = "team_ops"

# A new agent's caps are empty (no cap): a real agent can need many calls. Seeds set low ones.
GUARDRAILS: dict[str, Any] = {
    "redactPii": True,
    "maxToolCallsPerTurn": None,
    "maxModelCallsPerTurn": 50,
    "maxModelCallsPerConversation": None,
    "maxCostPerConversation": None,
    "whenUnsure": "handoff",
    "blockedTopics": [],
}
# A version saved before the model-call cap was a setting ran on the kernel's 8.
LEGACY_MODEL_CALLS = 8
# Model calls per turn when the builder leaves the field empty: never unlimited, since a looping agent would spend real
# calls until the deadline. Unlimited is a large number typed on purpose.
PLATFORM_MODEL_CALLS = 50
# A chat conversation's budget when the builder leaves the fields empty (c-103): never unlimited, so a conversation that
# loops on a real model pauses and asks a person to continue. Cost is in the price table's currency.
PLATFORM_CONVERSATION_CALLS = 200
PLATFORM_CONVERSATION_COST = 5.0
# What the runtime acts on, so the agent page offers only these (c-068 T004). Chat is the one channel an agent talks
# on; of the guardrail settings the tool-call and model-call caps reach a turn (definition_of), topics are blocked
# through pinned guardrails; no eval service runs, so the page shows no evals.
CONTROLS: dict[str, Any] = {
    "channels": ["chat"],
    "guardrails": [
        # Masks personal data in what a turn shows and returns (c-293).
        "redactPii",
        "maxToolCallsPerTurn",
        "maxModelCallsPerTurn",
        "maxModelCallsPerConversation",
        "maxCostPerConversation",
    ],
    "evals": False,
}


def spec_from_seed(a: AgentDefinition, model: str) -> dict[str, Any]:
    """A seeded agent's spec. Its instruction fragments are kept, so publishing it unchanged serves the same prompt."""
    return {
        "name": a.name,
        "role": a.role,
        "model": model,
        "channels": ["chat"],
        "instructions": "\n\n".join(f.text for f in a.instructions),
        "fragments": [f.model_dump() for f in a.instructions],
        "toolIds": list(a.tools),
        "collections": list(a.default_kb_ids),
        "suggestions": list(a.suggestions),
        # Seeds keep low caps (the seed's tool calls, the kernel's 8 model calls); a real agent sets its own.
        "guardrails": {
            **GUARDRAILS,
            "maxToolCallsPerTurn": a.max_tool_calls,
            "maxModelCallsPerTurn": a.max_model_calls,
        },
    }


def _cap(spec: dict[str, Any], key: str, legacy: int | None) -> int | None:
    """A per-turn cap from the version: a number, or None for no cap; `legacy` when the version predates the key."""
    caps = cast(dict[str, Any], spec.get("guardrails") or {})
    if key not in caps:
        return legacy
    return None if caps[key] is None else int(caps[key])


def memory_of(spec: dict[str, Any]) -> dict[str, Any]:
    """The agent's memory setting (c-124): on with every kind unless the spec says otherwise."""
    return {"enabled": True, "kinds": ["fact", "preference", "episode"], **(spec.get("memory") or {})}


def definition_of(agent_id: str, version: int, spec: dict[str, Any]) -> AgentDefinition:
    """The catalogue definition the runtime serves for one version."""
    text: str = spec.get("instructions") or ""
    raw: list[dict[str, Any]] = spec.get("fragments") or []
    fragments = [Fragment.model_validate(f) for f in raw]
    if not fragments or "\n\n".join(f.text for f in fragments) != text:
        fragments = [Fragment(text=text or f"You are {spec['name']}. {spec['role']}")]
    widget_settings = cast(dict[str, Any], spec.get("widgets") or {})
    caps = cast(dict[str, Any], spec.get("guardrails") or {})
    return AgentDefinition(
        id=agent_id,
        name=spec["name"],
        role=spec["role"],
        version=version,
        instructions=fragments,
        tools=list(spec.get("toolIds") or []),
        default_kb_ids=list(spec.get("collections") or []),
        suggestions=list(spec.get("suggestions") or []),
        max_tool_calls=_cap(spec, "maxToolCallsPerTurn", None),
        max_model_calls=_cap(spec, "maxModelCallsPerTurn", LEGACY_MODEL_CALLS) or PLATFORM_MODEL_CALLS,
        max_conversation_calls=_cap(spec, "maxModelCallsPerConversation", None) or PLATFORM_CONVERSATION_CALLS,
        max_conversation_cost=float(caps.get("maxCostPerConversation") or PLATFORM_CONVERSATION_COST),
        redact_pii=bool(caps.get("redactPii", True)),
        guardrails=[GuardrailRule.model_validate(p) for p in cast(list[Any], spec.get("guardrailPins") or [])],
        skills=[SkillPinRule.model_validate(p) for p in cast(list[Any], spec.get("skillPins") or [])],
        model_alias=spec.get("model") or None,
        limits=limits_of(spec),
        widgets=[WidgetPinRule.model_validate(p) for p in cast(list[Any], spec.get("widgetPins") or [])],
        compose=bool(widget_settings.get("compose", False)),
        widgets_per_turn=cast(int | None, widget_settings.get("perTurn")),
        memory_enabled=bool(memory_of(spec)["enabled"]),
        memory_kinds=tuple(memory_of(spec)["kinds"]),
    )


def agent_review_body(
    agent_id: str, spec: dict[str, Any], row: dict[str, Any], v: dict[str, Any], *, note: str, by: str
) -> dict[str, Any]:
    """The body of an `agent_publish` review for version `v`."""
    return {
        "agentId": agent_id,
        "agentName": spec["name"],
        "version": v["version"],
        "fromVersion": row["published_version"],
        "note": note,
        "requestedBy": by,
        "savedBy": v["saved_by"],
        "tier": "low",
        "tierReason": "No live workflow pins it",
        "approvalsNeeded": 1,
        "candidate": None,
        "published": None,
        "failing": 0,
        "blockers": [],
        "changes": v["changes"],
        # The reviewer approves what callers may change along with the agent itself.
        "limits": limits_of(spec).wire(),
        # And sees each pinned guardrail with its switch: one off is not checked once this version is live.
        "guardrailPins": [
            {
                "guardrailId": p["guardrailId"],
                "version": p["version"],
                "name": p["name"],
                "enabled": p.get("enabled", True),
            }
            for p in cast(list[dict[str, Any]], spec.get("guardrailPins") or [])
        ],
    }


SEED_BY = "seed"


async def seed_agent_version(
    rt: Runtime, agent_id: str, change: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]], note: str
) -> None:
    """A seed's change to an agent (a pinned guardrail or skill) as a new version from the published spec: published
    at once in dev, through an `agent_publish` review elsewhere. A draft a person saved is never stepped over: the
    seed waits, and the person can pin it themselves."""
    reg = registry(rt)
    row = await reg.row(agent_id)
    if row["published_version"] is None:
        return
    newest = await reg.version(agent_id, int(row["version"]))
    if row["version"] != row["published_version"] and newest["saved_by"] != SEED_BY:
        log.info("seed_agent_change_deferred", agent=agent_id, note=note, draft_saved_by=newest["saved_by"])
        return
    if any(r["status"] == "pending" for r in await reg.requests("agent", agent_id)):
        log.info("seed_agent_change_deferred", agent=agent_id, note=note, reason="review open")
        return
    live = dict((await reg.version(agent_id, int(row["published_version"])))["spec"])
    spec = await change(dict(live))
    n = await reg.save(agent_id, spec, by=SEED_BY, note=note)
    # A seed's change follows the team's policy like a person's publish (c-086).
    from .publish_policy import decide  # noqa: PLC0415 - publish_policy imports this module's callers' layer

    decision = await decide(rt, area="agents", team_id=row["team_id"], old=live, new=spec)
    if not decision.review_required:
        await reg.publish(agent_id, n, by=SEED_BY, review_id="seed")
        if not row["paused"]:
            go_live(rt, agent_id, n, spec)
        return
    v = await reg.version(agent_id, n)
    body = {**agent_review_body(agent_id, spec, row, v, note=note, by=SEED_BY), **decision.record()}
    await reg.open_request("agent", agent_id, n, note=note, by=SEED_BY, body=body, approved=False)


def require_owner_or_admin(me: Principal, *, area: str, team_id: str, created_by: str, what: str) -> None:
    """Deleting a shared rule or procedure (`skills` or `guardrails` delete): an admin of the team that owns it, or
    whoever created it, whatever their role now (`own` in every member role's grid)."""
    can(caller_of(me), area, "delete", team=team_id, owner=created_by, what=what)


def registry(rt: Runtime) -> AgentRegistry:
    return AgentRegistry(rt.db)


def go_live(rt: Runtime, agent_id: str, version: int, spec: dict[str, Any]) -> None:
    """Serves `version`: its definition in the catalogue and the agent's own graph under `agent:<id>`."""
    rt.catalog.put_agent(definition_of(agent_id, version, spec))
    if rt.agent_graph is not None:
        rt.graphs[f"agent:{agent_id}"] = rt.agent_graph(agent_id)


def take_down(rt: Runtime, agent_id: str) -> None:
    """Out of service: no new chat, turn or thread. The agent's graph stays compiled so a turn under way, or one paused
    at an approval, still resumes and finishes (drain, not cut: definitions-and-versions.md)."""
    rt.catalog.drop_agent(agent_id)


async def pinned_definition(rt: Runtime, agent_id: str, version: int) -> AgentDefinition | None:
    """The agent at a published version a deployment pins (c-117), from the registry store, kept in the catalogue so the
    chat graph serves it; None when that version was never published."""
    if (known := rt.catalog.agent_at(agent_id, version)) is not None:
        return known
    spec = await registry(rt).published_spec(agent_id, version)
    if spec is None:
        return None
    definition = definition_of(agent_id, version, spec)
    rt.catalog.put_pinned(definition)
    return definition


async def refuse_new_turns(rt: Runtime, agent_id: str) -> None:
    """Raises 409 `agent_paused` when the agent is paused; new conversations, messages and turns wait for a resume."""
    if rt.catalog.agent(agent_id) is not None:
        return
    try:
        row = await registry(rt).row(agent_id)
    except NotFound:
        return
    if row["paused"]:
        name = rt.catalog.agent_in_flight(agent_id)
        label = name.name if name else agent_id
        raise Conflict(
            f"{label} is paused, so it takes no new messages. A reply already under way finishes.",
            code="agent_paused",
        )


# What the seed file decides about a seeded agent; the model, pins and limits are left to the version.
SEED_FIELDS = ("name", "role", "instructions", "fragments", "toolIds", "collections", "suggestions")


async def follow_seed(rt: Runtime, a: AgentDefinition, row: dict[str, Any]) -> None:
    """A seeded agent whose published version the seed still owns (saved by the seed) takes the seed file's change as
    a new version, so editing the seed reaches a database seeded before it. Once a person has published a version the
    agent is theirs and the seed leaves it alone."""
    if row["published_version"] is None:
        return
    reg = registry(rt)
    published = await reg.version(a.id, int(row["published_version"]))
    if published["saved_by"] != SEED_BY:
        return
    want = {k: v for k, v in spec_from_seed(a, rt.settings.model_alias).items() if k in SEED_FIELDS}
    spec = cast(dict[str, Any], published["spec"])
    if all(spec.get(k) == v for k, v in want.items()):
        return

    async def change(s: dict[str, Any]) -> dict[str, Any]:
        return {
            **s,
            **want,
            "guardrails": {
                **(s.get("guardrails") or GUARDRAILS),
                "maxToolCallsPerTurn": a.max_tool_calls,
                "maxModelCallsPerTurn": a.max_model_calls,
            },
        }

    await seed_agent_version(rt, a.id, change, "Seed updated")


async def load(rt: Runtime, seed: Catalog) -> None:
    """At start: seeds a row for each catalogue agent that has none, brings a seeded agent the seed still owns up to
    its seed file (`follow_seed`; one a person has published is left alone), then serves exactly the published,
    unpaused versions, so a seeded agent that was paused or deleted stays that way across a restart."""
    reg = registry(rt)
    have = {r["id"]: r for r in await reg.rows()}
    for a in list(seed.agents):
        if a.id not in have:
            spec = spec_from_seed(a, rt.settings.model_alias)
            await reg.create(spec, by="seed", team_id=SEED_TEAM, agent_id=a.id, version=a.version, published=True)
        else:
            await follow_seed(rt, a, have[a.id])
    rows = {r["id"]: r for r in await reg.rows()}
    for a in list(rt.catalog.agents):
        if a.id not in rows:
            take_down(rt, a.id)
    for aid, r in rows.items():
        if r["published_version"] is None or r["paused"]:
            take_down(rt, aid)
            continue
        v = await reg.version(aid, int(r["published_version"]))
        go_live(rt, aid, int(r["published_version"]), v["spec"])


async def tasks_24h(rt: Runtime) -> dict[str, int]:
    """Threads started in the last day, by agent id: chats (`agent_wrapper` threads naming the agent in their meta) and
    threads on the agent's own graph."""
    since = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    out: dict[str, int] = {}
    for graph, meta in await GraphStore(rt.db).agent_threads_since(since):
        if meta.get("test"):
            continue  # a builder's test is not a task the agent did (c-284)
        aid = graph.removeprefix("agent:") if graph != "agent_wrapper" else str(meta.get("agentId") or "")
        if aid:
            out[aid] = out.get(aid, 0) + 1
    return out


def version_state(row: dict[str, Any], v: int, pending: dict[str, Any] | None, rejected: set[int]) -> str:
    if v in rejected:
        return "rejected"
    if pending is not None and pending["version"] == v:
        return "in_review"
    pub = row["published_version"]
    if v == pub:
        return "published"
    if pub is not None and v < pub:
        return "superseded"
    return "superseded" if v < row["version"] else "draft"


def agent_view(row: dict[str, Any], spec: dict[str, Any], tasks: int) -> dict[str, Any]:
    published = row["published_version"]
    availability = "paused" if row["paused"] else "published" if published is not None else "not_published"
    return {
        "id": row["id"],
        "name": spec["name"],
        "slug": row["slug"],
        "role": spec["role"],
        "instructions": spec.get("instructions") or "",
        "model": spec["model"],
        "channels": spec.get("channels") or [],
        "toolIds": spec.get("toolIds") or [],
        "collections": spec.get("collections") or [],
        # The owning team comes from the creator's token (c-171); the console names it from its teams list.
        "teamId": row["team_id"],
        "paused": bool(row["paused"]),
        "availability": availability,
        "version": row["version"],
        "publishedVersion": published,
        "updatedAt": row["updated_at"],
        "tasks24h": tasks,
        # Needs resolution outcomes per thread, which no table records yet.
        "autoResolvedRate": 0,
        "workflowIds": [],
        "guardrails": spec.get("guardrails") or GUARDRAILS,
        "guardrailPins": [
            {
                "guardrailId": p["guardrailId"],
                "version": p["version"],
                "name": p["name"],
                "topics": p["topics"],
                "enabled": bool(p.get("enabled", True)),
            }
            for p in cast(list[dict[str, Any]], spec.get("guardrailPins") or [])
        ],
        **({"wrapperWorkflowId": f"agent:{row['id']}"} if published is not None else {}),
        "limits": limits_of(spec).wire(),
        "widgetPins": [
            {
                "widgetId": p["widgetId"],
                "version": p["version"],
                "name": p["name"],
                "requiresTools": required_tools(p.get("tree")),
            }
            for p in cast(list[dict[str, Any]], spec.get("widgetPins") or [])
        ],
        "widgets": {"compose": False, "perTurn": None, **(spec.get("widgets") or {})},
        "memory": memory_of(spec),
        "controls": CONTROLS,
        "usedIn": [],
    }


# Kept on a workflow request for its decision to publish, and left out of the Review the console reads.
STORED_ONLY = frozenset({"definition", "graph"})


def _sla_minutes(req: dict[str, Any], now: datetime, hours: float) -> int | None:
    """Minutes left before the request is overdue, from when it was asked; negative once overdue, and None once
    decided, since a decided review has no deadline left."""
    if req["status"] not in ("pending", "in_review"):
        return None
    asked = datetime.fromisoformat(str(req["created_at"]).replace("Z", "+00:00"))
    return int((asked + timedelta(hours=hours) - now).total_seconds() // 60)


def review_view(
    req: dict[str, Any], *, name: str, slug: str, sla_hours: float, now: datetime | None = None
) -> dict[str, Any]:
    """A publish request as the console's Review, kind `agent_publish` or `publish_request`. `sla_hours` is the
    tenant's review deadline (`review_sla.sla_hours`). A decided one says who decided it, when and why."""
    agent = req["kind"] == "agent"
    body = req["body"]
    return {
        "id": req["id"],
        "title": f"Publish {name} v{req['version']}",
        "customer": f"Requested by {requester(str(req['requested_by']))}",
        "workflowId": "" if agent else req["subject_id"],
        "workflowName": name,
        "agentSlug": slug if agent else "",
        "agentName": name if agent else None,
        "kind": "agent_publish" if agent else "publish_request",
        "risk": body.get("tier", "low"),
        "confidence": 1,
        "proposal": req["note"],
        "actionTool": "publish_agent" if agent else "publish_workflow",
        "currency": "CAD",
        "policy": {
            "id": "gp_agent_publish" if agent else "gp_workflow_publish",
            "name": "Agent publish" if agent else "Workflow publish",
            "condition": "every version before it serves",
            "reviewers": "publishers",
            "sla": "1 business day",
            "onTimeout": "Stays pending; the requester is notified",
            "fourEyes": False,
        },
        "slaMinutes": _sla_minutes(req, now or datetime.now(UTC), sla_hours),
        "approvals": [req["decided_by"]] if req["decided_by"] else [],
        **({"decidedBy": req["decided_by"]} if req["decided_by"] else {}),
        "status": req["status"],
        "createdAt": req["created_at"],
        **({"decidedAt": req["decided_at"]} if req["decided_at"] else {}),
        "reasoning": body.get("changes", []),
        "evidence": [],
        **({"agentPublish": body} if agent else {"publish": {k: v for k, v in body.items() if k not in STORED_ONLY}}),
        **({"decisionReason": req["decision_reason"]} if req.get("decision_reason") else {}),
    }


def require_newest_draft(row: dict[str, Any], version: int) -> None:
    if version != row["version"]:
        raise Unprocessable(f"v{version} is not the newest draft (v{row['version']}).", code="not_newest_draft")
    if row["published_version"] == version:
        raise Unprocessable(f"v{version} is already published.", code="already_published")
