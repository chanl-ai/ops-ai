"""The agent registry: agents as rows with immutable versions, a published pointer and publish requests.

Every save is a new version holding the whole spec (instructions, model, tools, knowledge bases, guardrails). The
published pointer names the version the runtime serves: publishing it puts that version's definition in the catalogue,
where chat and the agent graphs read agents, and compiles the agent's own one-node graph, `agent:<id>`. Drafts never
reach the catalogue, so editing an agent changes nothing live until a publish.

Publish requests are shared with workflows (`kind`). Under `registry_auto_approve` in dev a request is approved as it
is made; elsewhere it stays pending until a reviewer decides it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ops_agents.activities.catalog import AgentDefinition, Catalog, Fragment
from ops_service_kit.errors import Conflict, NotFound, Unprocessable

from ..store.agent_registry import (
    AgentRegistry,
)
from ..store.graphs import GraphStore
from .deps import Runtime

# The team that owns every seeded agent and workflow: Operations, under the id platform-service's dev seed gives it, so
# agents-service, tools-service and platform-service name it the same way and no seed carries a placeholder team.
SEED_TEAM = "team_ops"

GUARDRAILS: dict[str, Any] = {"redactPii": True, "maxToolCallsPerTurn": 6, "whenUnsure": "handoff", "blockedTopics": []}


def spec_from_seed(a: AgentDefinition, model: str) -> dict[str, Any]:
    """A seeded agent's spec. Its instruction fragments are kept, so publishing it unchanged serves the same prompt."""
    return {
        "name": a.name,
        "role": a.role,
        "model": model,
        "owner": "Operations",
        "channels": ["chat"],
        "instructions": "\n\n".join(f.text for f in a.instructions),
        "fragments": [f.model_dump() for f in a.instructions],
        "toolIds": list(a.tools),
        "collections": list(a.default_kb_ids),
        "suggestions": list(a.suggestions),
        "guardrails": {**GUARDRAILS, "maxToolCallsPerTurn": a.max_tool_calls},
    }


def definition_of(agent_id: str, version: int, spec: dict[str, Any]) -> AgentDefinition:
    """The catalogue definition the runtime serves for one version."""
    text: str = spec.get("instructions") or ""
    raw: list[dict[str, Any]] = spec.get("fragments") or []
    fragments = [Fragment.model_validate(f) for f in raw]
    if not fragments or "\n\n".join(f.text for f in fragments) != text:
        fragments = [Fragment(text=text or f"You are {spec['name']}. {spec['role']}")]
    return AgentDefinition(
        id=agent_id,
        name=spec["name"],
        role=spec["role"],
        version=version,
        instructions=fragments,
        tools=list(spec.get("toolIds") or []),
        default_kb_ids=list(spec.get("collections") or []),
        suggestions=list(spec.get("suggestions") or []),
        max_tool_calls=int((spec.get("guardrails") or GUARDRAILS)["maxToolCallsPerTurn"]),
        model_alias=spec.get("model") or None,
    )


def auto_approves(rt: Runtime) -> bool:
    return rt.settings.registry_auto_approve and rt.settings.environment == "dev"


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


async def load(rt: Runtime, seed: Catalog) -> None:
    """At start: seeds a row for each catalogue agent that has none, then serves exactly the published, unpaused
    versions, so a seeded agent that was paused or deleted stays that way across a restart."""
    reg = registry(rt)
    have = {r["id"] for r in await reg.rows()}
    for a in list(seed.agents):
        if a.id not in have:
            spec = spec_from_seed(a, rt.settings.model_alias)
            await reg.create(spec, by="seed", team_id=SEED_TEAM, agent_id=a.id, version=a.version, published=True)
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
        "owner": spec["owner"],
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
        **({"wrapperWorkflowId": f"agent:{row['id']}"} if published is not None else {}),
        "usedIn": [],
    }


# Kept on a workflow request for its decision to publish, and left out of the Review the console reads.
STORED_ONLY = frozenset({"definition", "graph"})


def review_view(req: dict[str, Any], *, name: str, slug: str) -> dict[str, Any]:
    """A publish request as the console's Review, kind `agent_publish` or `publish_request`."""
    agent = req["kind"] == "agent"
    body = req["body"]
    return {
        "id": req["id"],
        "title": f"Publish {name} v{req['version']}",
        "customer": f"Requested by {req['requested_by']}",
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
        "slaMinutes": 8 * 60,
        "approvals": [req["decided_by"]] if req["decided_by"] else [],
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
