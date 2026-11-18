"""The agent registry: agents as rows with immutable versions, a published pointer and publish requests.

Every save is a new version holding the whole spec (instructions, model, tools, knowledge bases, guardrails). The
published pointer names the version the runtime serves: publishing it puts that version's definition in the catalogue,
where chat and the agent graphs read agents, and compiles the agent's own one-node graph, `agent:<id>`. Drafts never
reach the catalogue, so editing an agent changes nothing live until a publish.

Publish requests are shared with workflows (`kind`). Whether one is approved as it is made or waits for a reviewer is
the team's publish policy (api/publish_policy.py).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Required, TypedDict, cast

from ops_access import can
from ops_agent_kernel.layout import required_tools
from ops_agents.activities.agent_limits import limits_of
from ops_agents.activities.agent_limits import wire as wire_limits
from ops_agents.activities.catalog import AgentDefinition, Catalog, Fragment, GuardrailRule, SkillPinRule, WidgetPinRule
from ops_service_kit.errors import Conflict, NotFound, Unprocessable
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.logging import get_logger
from ops_store import isolation

from ..store.agent_registry import (
    AgentRegistry,
    AgentRow,
    AgentVersionRow,
    PublishRequestRow,
)
from ..store.graphs import GraphStore
from ..store.tenancy import SERVE_PUBLISHED
from .auth import Principal, caller_of
from .deps import Runtime
from .review_text import requester

# The team that owns every seeded agent and workflow: Operations, under the id platform-service's dev seed gives it, so
# agents-service, tools-service and platform-service name it the same way and no seed carries a placeholder team.
log = get_logger("ops_agents.agent_registry")
SEED_TEAM = "team_ops"


class AgentCaps(TypedDict, total=False):
    """A version's `guardrails`: the caps a turn and a conversation run under."""

    redactPii: bool
    maxToolCallsPerTurn: int | None
    maxModelCallsPerTurn: int | None
    maxModelCallsPerConversation: int | None
    maxCostPerConversation: float | None
    whenUnsure: str
    blockedTopics: list[str]


class AgentMemory(TypedDict):
    enabled: bool
    kinds: list[str]


class AgentWidgets(TypedDict, total=False):
    compose: bool
    perTurn: int | None


class GuardrailPin(TypedDict, total=False):
    """A spec's `guardrailPins` entry: the pinned guardrail version, as resolved when the version was saved."""

    guardrailId: Required[str]
    version: Required[int]
    name: Required[str]
    topics: Required[list[str]]
    enabled: bool


class WidgetPin(TypedDict, total=False):
    widgetId: Required[str]
    version: Required[int]
    name: Required[str]
    tree: JsonValue


class AgentSpec(TypedDict, total=False):
    """An agent version's stored `spec`, as this module reads it. A view of the stored document (cast, never
    rebuilt), so a version saved before a key existed reads exactly as it did."""

    name: Required[str]
    role: Required[str]
    model: Required[str]
    channels: list[str]
    instructions: str
    fragments: list[Json]
    toolIds: list[str]
    collections: list[str]
    allTeamKnowledgeBases: bool
    accounts: dict[str, str]
    suggestions: list[str]
    guardrails: AgentCaps
    guardrailPins: list[GuardrailPin]
    skillPins: list[Json]
    widgetPins: list[WidgetPin]
    widgets: AgentWidgets
    memory: AgentMemory
    skillMenu: Literal["team", "attached", "off"]


# A new agent's caps are empty (no cap): a real agent can need many calls. Seeds set low ones.
GUARDRAILS: Json = {
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
# A chat conversation's budget when the builder leaves the fields empty: never unlimited, so a conversation that
# loops on a real model pauses and asks a person to continue. Cost is in the price table's currency.
PLATFORM_CONVERSATION_CALLS = 200
PLATFORM_CONVERSATION_COST = 5.0
# What the runtime acts on, so the agent page offers only these. Chat is the one channel an agent talks
# on; of the guardrail settings the tool-call and model-call caps reach a turn (definition_of), topics are blocked
# through pinned guardrails; eval-runs score a dataset on the newest version.
CONTROLS: Json = {
    "channels": ["chat"],
    "guardrails": [
        # Masks personal data in what a turn shows and returns.
        "redactPii",
        "maxToolCallsPerTurn",
        "maxModelCallsPerTurn",
        "maxModelCallsPerConversation",
        "maxCostPerConversation",
    ],
    "evals": True,
}


def spec_from_seed(a: AgentDefinition, model: str) -> Json:
    """A seeded agent's spec. Its instruction fragments are kept, so publishing it unchanged serves the same prompt."""
    return {
        "name": a.name,
        "role": a.role,
        # A seed that names its own alias runs on it; the others on the runtime's.
        "model": a.model_alias or model,
        "channels": ["chat"],
        "instructions": "\n\n".join(f.text for f in a.instructions),
        "fragments": [f.model_dump() for f in a.instructions],
        "toolIds": list(a.tools),
        "collections": list(a.default_kb_ids),
        "allTeamKnowledgeBases": a.all_team_knowledge,
        "suggestions": list(a.suggestions),
        # Seeds keep low caps (the seed's tool calls, the kernel's 8 model calls); a real agent sets its own.
        "guardrails": {
            **GUARDRAILS,
            "maxToolCallsPerTurn": a.max_tool_calls,
            "maxModelCallsPerTurn": a.max_model_calls,
        },
    }


CapKey = Literal["maxToolCallsPerTurn", "maxModelCallsPerTurn", "maxModelCallsPerConversation"]


def _cap(spec: AgentSpec, key: CapKey, legacy: int | None) -> int | None:
    """A per-turn cap from the version: a number, or None for no cap; `legacy` when the version predates the key."""
    caps = spec.get("guardrails") or {}
    if key not in caps:
        return legacy
    if not isinstance(cast(object, caps), dict):
        # A version whose `guardrails` is not an object fails as indexing it always has.
        raise TypeError(f"guardrails is not an object: {caps!r}")
    value = caps.get(key)
    return None if value is None else int(value)


def memory_of(spec: Json) -> AgentMemory:
    """The agent's memory setting: on with every kind unless the spec says otherwise."""
    held = cast(AgentSpec, spec).get("memory") or {}
    return cast(AgentMemory, {"enabled": True, "kinds": ["fact", "preference", "episode"], **held})


def definition_of(agent_id: str, version: int, spec: Json) -> AgentDefinition:
    """The catalogue definition the runtime serves for one version."""
    s = cast(AgentSpec, spec)
    text = s.get("instructions") or ""
    raw = s.get("fragments") or []
    fragments = [Fragment.model_validate(f) for f in raw]
    if not fragments or "\n\n".join(f.text for f in fragments) != text:
        fragments = [Fragment(text=text or f"You are {s['name']}. {s['role']}")]
    widget_settings = s.get("widgets") or {}
    caps = s.get("guardrails") or {}
    return AgentDefinition(
        id=agent_id,
        name=s["name"],
        role=s["role"],
        version=version,
        instructions=fragments,
        tools=list(s.get("toolIds") or []),
        default_kb_ids=list(s.get("collections") or []),
        all_team_knowledge=bool(s.get("allTeamKnowledgeBases")),
        accounts={str(k): str(v) for k, v in dict(s.get("accounts") or {}).items()},
        suggestions=list(s.get("suggestions") or []),
        max_tool_calls=_cap(s, "maxToolCallsPerTurn", None),
        max_model_calls=_cap(s, "maxModelCallsPerTurn", LEGACY_MODEL_CALLS) or PLATFORM_MODEL_CALLS,
        max_conversation_calls=_cap(s, "maxModelCallsPerConversation", None) or PLATFORM_CONVERSATION_CALLS,
        max_conversation_cost=float(caps.get("maxCostPerConversation") or PLATFORM_CONVERSATION_COST),
        redact_pii=bool(caps.get("redactPii", True)),
        guardrails=[GuardrailRule.model_validate(p) for p in s.get("guardrailPins") or []],
        skills=[SkillPinRule.model_validate(p) for p in s.get("skillPins") or []],
        model_alias=s.get("model") or None,
        limits=limits_of(spec),
        widgets=[WidgetPinRule.model_validate(p) for p in s.get("widgetPins") or []],
        compose=bool(widget_settings.get("compose", False)),
        widgets_per_turn=widget_settings.get("perTurn"),
        memory_enabled=bool(memory_of(spec)["enabled"]),
        memory_kinds=tuple(memory_of(spec)["kinds"]),
        skill_menu=s.get("skillMenu") or "team",
    )


def agent_review_body(agent_id: str, spec: Json, row: AgentRow, v: AgentVersionRow, *, note: str, by: str) -> Json:
    """The body of an `agent_publish` review for version `v`."""
    s = cast(AgentSpec, spec)
    return {
        "agentId": agent_id,
        "agentName": s["name"],
        "version": v.version,
        "fromVersion": row.published_version,
        "note": note,
        "requestedBy": by,
        "savedBy": v.saved_by,
        "tier": "low",
        "tierReason": "No live workflow pins it",
        "approvalsNeeded": 1,
        "candidate": None,
        "published": None,
        "failing": 0,
        "blockers": [],
        "changes": v.changes,
        # The reviewer approves what callers may change along with the agent itself.
        "limits": wire_limits(limits_of(spec)),
        # And sees each pinned guardrail with its switch: one off is not checked once this version is live.
        "guardrailPins": [
            {
                "guardrailId": p["guardrailId"],
                "version": p["version"],
                "name": p["name"],
                "enabled": p.get("enabled", True),
            }
            for p in s.get("guardrailPins") or []
        ],
    }


SEED_BY = "seed"


async def seed_agent_version(
    rt: Runtime,
    agent_id: str,
    change: Callable[[Json], Awaitable[Json]],
    note: str,
    *,
    by: str = SEED_BY,
) -> None:
    """A seed's change to an agent (a pinned guardrail or skill) as a new version from the published spec: published
    at once in dev, through an `agent_publish` review elsewhere. A draft a person saved is never stepped over: the
    seed waits, and the person can pin it themselves. `by` is who the change is recorded as made by: the seed, or the
    platform for a team's Ops Assistant."""
    reg = registry(rt)
    row = await reg.row(agent_id)
    if row.published_version is None:
        return
    newest = await reg.version(agent_id, row.version)
    if row.version != row.published_version and newest.saved_by != by:
        log.info("seed_agent_change_deferred", agent=agent_id, note=note, draft_saved_by=newest.saved_by)
        return
    if any(r.status == "pending" for r in await reg.requests("agent", agent_id)):
        log.info("seed_agent_change_deferred", agent=agent_id, note=note, reason="review open")
        return
    live = dict((await reg.version(agent_id, row.published_version)).spec)
    spec = await change(dict(live))
    n = await reg.save(agent_id, spec, by=by, note=note)
    # A seed's change follows the team's policy like a person's publish.
    from .publish_policy import decide  # noqa: PLC0415 - publish_policy imports this module's callers' layer

    decision = await decide(rt, area="agents", team_id=row.team_id, old=live, new=spec)
    if not decision.review_required:
        await reg.publish(agent_id, n, by=by, review_id="seed")
        if not row.paused:
            go_live(rt, agent_id, n, spec)
        return
    v = await reg.version(agent_id, n)
    body = {**agent_review_body(agent_id, spec, row, v, note=note, by=by), **decision.record()}
    await reg.open_request("agent", agent_id, n, note=note, by=by, body=body, approved=False)


def require_owner_or_admin(me: Principal, *, area: str, team_id: str, created_by: str, what: str) -> None:
    """Deleting a shared rule or procedure (`skills` or `guardrails` delete): an admin of the team that owns it, or
    whoever created it, whatever their role now (`own` in every member role's grid)."""
    can(caller_of(me), area, "delete", team=team_id, owner=created_by, what=what)


def registry(rt: Runtime) -> AgentRegistry:
    return AgentRegistry(rt.db)


def go_live(rt: Runtime, agent_id: str, version: int, spec: Json) -> None:
    """Serves `version`: its definition in the catalogue and the agent's own graph under `agent:<id>`."""
    rt.catalog.put_agent(definition_of(agent_id, version, spec))
    if rt.agent_graph is not None:
        rt.graphs[f"agent:{agent_id}"] = rt.agent_graph(agent_id)


def take_down(rt: Runtime, agent_id: str) -> None:
    """Out of service: no new chat, turn or thread. The agent's graph stays compiled so a turn under way, or one paused
    at an approval, still resumes and finishes (drain, not cut: definitions-and-versions.md)."""
    rt.catalog.drop_agent(agent_id)


async def live_agent(rt: Runtime, agent_id: str) -> AgentDefinition | None:
    """The live agent `agent_id` when the caller's tenant holds it; None when it is not live or the tenant holds none,
    for a route that takes the id from the caller's own records (a thread, the team's default)."""
    if agent_id not in await registry(rt).tenant_owners({agent_id}):
        return None
    return rt.catalog.agent(agent_id)


async def in_flight_agent(rt: Runtime, agent_id: str) -> AgentDefinition | None:
    """`live_agent`, or the definition a turn under way started on after the agent was paused (it may finish)."""
    if agent_id not in await registry(rt).tenant_owners({agent_id}):
        return None
    return rt.catalog.agent_in_flight(agent_id)


async def pinned_definition(rt: Runtime, agent_id: str, version: int) -> AgentDefinition | None:
    """The agent at a published version a deployment pins, from the registry store, kept in the catalogue so the
    chat graph serves it; None when that version was never published or the caller's tenant holds no such agent (the
    catalogue holds every tenant's)."""
    if agent_id not in await registry(rt).tenant_owners({agent_id}):
        return None
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
    if agent_id not in await registry(rt).tenant_owners({agent_id}):
        return  # another tenant's agent: the caller's route answers NotFound, never its name or state
    if rt.catalog.agent(agent_id) is not None:
        return
    try:
        row = await registry(rt).row(agent_id)
    except NotFound:
        return
    if row.paused:
        name = rt.catalog.agent_in_flight(agent_id)
        label = name.name if name else agent_id
        raise Conflict(
            f"{label} is paused, so it takes no new messages. A reply already under way finishes.",
            code="agent_paused",
        )


# What the seed file decides about a seeded agent; the model, pins and limits are left to the version.
SEED_FIELDS = (
    "name",
    "role",
    "instructions",
    "fragments",
    "toolIds",
    "collections",
    "allTeamKnowledgeBases",
    "suggestions",
)


async def follow_seed(rt: Runtime, a: AgentDefinition, row: AgentRow) -> None:
    """A seeded agent whose published version the seed still owns (saved by the seed) takes the seed file's change as
    a new version, so editing the seed reaches a database seeded before it. Once a person has published a version the
    agent is theirs and the seed leaves it alone."""
    if row.published_version is None:
        return
    reg = registry(rt)
    published = await reg.version(a.id, row.published_version)
    if published.saved_by != SEED_BY:
        return
    want = {k: v for k, v in spec_from_seed(a, rt.settings.model_alias).items() if k in SEED_FIELDS}
    spec = published.spec
    if all(spec.get(k) == v for k, v in want.items()):
        return

    async def change(s: Json) -> Json:
        return {
            **s,
            **want,
            "guardrails": {
                **cast(Json, s.get("guardrails") or GUARDRAILS),
                "maxToolCallsPerTurn": a.max_tool_calls,
                "maxModelCallsPerTurn": a.max_model_calls,
            },
        }

    await seed_agent_version(rt, a.id, change, "Seed updated")


async def load(rt: Runtime, seed: Catalog) -> None:
    """At start, inside the seed's tenant: seeds a row for each catalogue agent that has none and brings a seeded agent
    the seed still owns up to its seed file (`follow_seed`; one a person has published is left alone). A seed id or
    slug already held outside the seed's tenant is skipped with a warning, and the service starts without it. Serving
    is `serve_published`, for every tenant."""
    reg = registry(rt)
    have = {r.id: r for r in await reg.rows()}
    for a in list(seed.agents):
        if a.id not in have:
            spec = spec_from_seed(a, rt.settings.model_alias)
            if not await reg.create_if_absent(spec, by=SEED_BY, team_id=SEED_TEAM, agent_id=a.id, version=a.version):
                log.warning("seed_agent_held_elsewhere", agent=a.id)
        else:
            await follow_seed(rt, a, have[a.id])


async def serve_published(rt: Runtime) -> None:
    """At start: serves exactly every tenant's published, unpaused versions, so an agent that was paused or deleted
    stays that way across a restart. One read past the tenant finds the pointers, then each tenant's specs are read
    under its own; a failure in one tenant is logged and the others are served."""
    reg = registry(rt)
    wanted: dict[str, set[tuple[str, int]]] = {}
    for tenant_id, aid, published, paused in await reg.published_pointers():
        if published is not None and not paused:
            wanted.setdefault(tenant_id, set()).add((aid, published))
    served = {aid for keys in wanted.values() for aid, _ in keys}
    for a in list(rt.catalog.agents):
        if a.id not in served:
            take_down(rt, a.id)
    for tenant_id, keys in wanted.items():
        try:
            with isolation.tenant_wide(SERVE_PUBLISHED, tenant_id=tenant_id):
                specs = await reg.published_specs(keys)
        except Exception as e:  # one tenant's failure must not stop the others, nor the service's start
            log.warning("serve_published_failed", tenant=tenant_id, error=type(e).__name__)
            continue
        for (aid, n), spec in specs.items():
            go_live(rt, aid, n, spec)


def a_day_ago() -> str:
    """The start of an agent's `tasks24h` window, as thread times are written."""
    return (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def tasks_24h(rt: Runtime) -> dict[str, int]:
    """Threads started in the last day, by agent id: chats (`agent_wrapper` threads naming the agent in their meta) and
    threads on the agent's own graph."""
    since = a_day_ago()
    out: dict[str, int] = {}
    for graph, meta in await GraphStore(rt.db).agent_threads_since(since):
        if meta.get("test"):
            continue  # a builder's test is not a task the agent did
        aid = graph.removeprefix("agent:") if graph != "agent_wrapper" else str(meta.get("agentId") or "")
        if aid:
            out[aid] = out.get(aid, 0) + 1
    return out


def version_state(row: AgentRow, v: int, pending: PublishRequestRow | None, rejected: set[int]) -> str:
    if v in rejected:
        return "rejected"
    if pending is not None and pending.version == v:
        return "in_review"
    pub = row.published_version
    if v == pub:
        return "published"
    if pub is not None and v < pub:
        return "superseded"
    return "superseded" if v < row.version else "draft"


def agent_view(row: Mapping[str, JsonValue], spec: Json, tasks: int) -> dict[str, Any]:
    """An agent's reply. Returned loose: the agents route adds keys of its own (`staleToolIds`, `usedIn`) to it."""
    s = cast(AgentSpec, spec)
    published = row["published_version"]
    availability = "paused" if row["paused"] else "published" if published is not None else "not_published"
    return {
        "id": row["id"],
        "name": s["name"],
        "slug": row["slug"],
        "role": s["role"],
        "instructions": s.get("instructions") or "",
        "model": s["model"],
        "channels": s.get("channels") or [],
        "toolIds": s.get("toolIds") or [],
        "collections": s.get("collections") or [],
        "allTeamKnowledgeBases": bool(s.get("allTeamKnowledgeBases")),
        "skillMenu": s.get("skillMenu") or "team",
        "accounts": dict(s.get("accounts") or {}),
        # The owning team comes from the creator's token; the console names it from its teams list.
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
        "guardrails": s.get("guardrails") or GUARDRAILS,
        "guardrailPins": [
            {
                "guardrailId": p["guardrailId"],
                "version": p["version"],
                "name": p["name"],
                "topics": p["topics"],
                "enabled": bool(p.get("enabled", True)),
            }
            for p in s.get("guardrailPins") or []
        ],
        **({"wrapperWorkflowId": f"agent:{row['id']}"} if published is not None else {}),
        "limits": wire_limits(limits_of(spec)),
        "widgetPins": [
            {
                "widgetId": p["widgetId"],
                "version": p["version"],
                "name": p["name"],
                "requiresTools": required_tools(p.get("tree")),
            }
            for p in s.get("widgetPins") or []
        ],
        "widgets": {"compose": False, "perTurn": None, **(s.get("widgets") or {})},
        "memory": memory_of(spec),
        "controls": CONTROLS,
        "usedIn": [],
    }


# Kept on a workflow request for its decision to publish, and left out of the Review the console reads.
STORED_ONLY = frozenset({"definition", "graph"})


def _sla_minutes(req: PublishRequestRow, now: datetime, hours: float) -> int | None:
    """Minutes left before the request is overdue, from when it was asked; negative once overdue, and None once
    decided, since a decided review has no deadline left."""
    if req.status not in ("pending", "in_review"):
        return None
    asked = datetime.fromisoformat(str(req.created_at).replace("Z", "+00:00"))
    return int((asked + timedelta(hours=hours) - now).total_seconds() // 60)


def review_view(
    req: PublishRequestRow, *, name: str, slug: str, sla_hours: float, now: datetime | None = None
) -> dict[str, Any]:
    """A publish request as the console's Review, kind `agent_publish` or `publish_request`. `sla_hours` is the
    tenant's review deadline (`review_sla.sla_hours`). A decided one says who decided it, when and why."""
    agent = req.kind == "agent"
    body = req.body
    return {
        "id": req.id,
        "title": f"Publish {name} v{req.version}",
        "customer": f"Requested by {requester(str(req.requested_by))}",
        "workflowId": "" if agent else req.subject_id,
        "workflowName": name,
        "agentSlug": slug if agent else "",
        "agentName": name if agent else None,
        "kind": "agent_publish" if agent else "publish_request",
        "risk": body.get("tier", "low"),
        "confidence": 1,
        "proposal": req.note,
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
        "approvals": [req.decided_by] if req.decided_by else [],
        **({"decidedBy": req.decided_by} if req.decided_by else {}),
        "status": req.status,
        "createdAt": req.created_at,
        **({"decidedAt": req.decided_at} if req.decided_at else {}),
        "reasoning": body.get("changes", []),
        "evidence": [],
        **({"agentPublish": body} if agent else {"publish": {k: v for k, v in body.items() if k not in STORED_ONLY}}),
        **({"decisionReason": req.decision_reason} if req.decision_reason else {}),
    }


def require_newest_draft(row: AgentRow, version: int) -> None:
    if version != row.version:
        raise Unprocessable(f"v{version} is not the newest draft (v{row.version}).", code="not_newest_draft")
    if row.published_version == version:
        raise Unprocessable(f"v{version} is already published.", code="already_published")
