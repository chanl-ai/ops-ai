"""The workflow registry: console workflows as rows, a canvas draft, and published versions that are definitions.

A workflow's id is its definition name, so `POST /v1/threads {graph: <id>}` starts it. The console draws a graph
(nodes and edges with console types); `compile_graph` turns it into a `WorkflowDefinition`, and publishing stores
that in `graph_versions` with its digest. The row's pointer names the version new threads start on.

Console node types map onto definition kinds: trigger → pass (the entry), step → agent_turn when it names an agent
(`data.agentSlug`, pinned to that agent's published version) and pass otherwise, review → human followed by a
decision condition built from its approved and rejected edges, branch or router with several routes → a route
condition (`_route_condition`), end → end. A node that carries `data.definition`
({kind, config}) is passed through unchanged, which is how a definition written as JSON (dispute_email) round-trips
through the canvas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ops_agents.graphs.definition import InvalidDefinitionError, NodeKind, WorkflowDefinition, validate
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger

from ..store.graphs import GraphStore
from ..store.workflow_registry import (
    WorkflowRegistry,
)
from .agent_registry import SEED_TEAM, definition_of
from .agent_registry import registry as agent_registry
from .deps import Runtime

log = get_logger("ops_agents.workflow_registry")

PASSTHROUGH_EDGE_KEYS = ("pass", "fail", "approved", "rejected", "default")


def condition_targets(config: dict[str, Any]) -> list[tuple[str, str]]:
    """(handle, target) for each route a condition's config names: its fixed keys, then a route rule's routes."""
    out = [(k, str(config[k])) for k in PASSTHROUGH_EDGE_KEYS if k in config]
    routes: list[dict[str, Any]] = config.get("routes") or []
    return out + [(f"route{i}", str(r["to"])) for i, r in enumerate(routes)]


# ── compile ──


@dataclass(frozen=True)
class Check:
    id: str
    name: str
    passed: bool
    failure: str | None = None

    def result(self) -> dict[str, Any]:
        outcome: dict[str, Any] = {"passed": self.passed, "paused": False, "toolsCalled": [], "reply": ""}
        if self.failure:
            outcome["failure"] = self.failure
        return {"caseId": self.id, "caseName": self.name, "draft": outcome, "live": None, "regression": False}


@dataclass(frozen=True)
class PinnedAgent:
    id: str
    slug: str
    version: int
    spec: dict[str, Any]


@dataclass(frozen=True)
class Compiled:
    definition: WorkflowDefinition | None
    checks: list[Check]
    agent_slugs: list[str]

    @property
    def failing(self) -> int:
        return sum(1 for c in self.checks if not c.passed)


def compile_graph(name: str, graph: dict[str, Any], agents: dict[str, PinnedAgent | None]) -> Compiled:
    """`agents` maps each slug the console knows to its published pin, or None for an agent with no published
    version. Returns the definition (None when any check fails) and every check that ran."""
    checks: list[Check] = []
    nodes: list[dict[str, Any]] = list(graph.get("nodes") or [])
    edges: list[dict[str, Any]] = list(graph.get("edges") or [])
    out_nodes: list[dict[str, Any]] = []
    out_edges: list[tuple[str, str]] = []
    skip_edges: set[int] = set()
    slugs: list[str] = []
    entry: list[str] = []
    by_id = {str(n["id"]): n for n in nodes}

    def outgoing(nid: str) -> list[tuple[int, dict[str, Any]]]:
        return [(i, e) for i, e in enumerate(edges) if e["source"] == nid]

    for n in nodes:
        nid, kind_of, data = str(n["id"]), str(n.get("type")), dict(n.get("data") or {})
        label = str(data.get("label") or nid)
        passthrough = data.get("definition")
        if isinstance(passthrough, dict):
            raw: dict[str, Any] = passthrough  # pyright: ignore[reportUnknownVariableType]
            config: dict[str, Any] = dict(raw.get("config") or {})
            out_nodes.append({"id": nid, "kind": raw["kind"], "config": config})
            if data.get("entry"):
                entry.append(nid)
            if raw["kind"] == "condition":
                # The condition's config names its targets; the drawn edges only show them.
                skip_edges.update(i for i, _ in outgoing(nid))
            continue
        if kind_of == "trigger":
            entry.append(nid)
            out_nodes.append({"id": nid, "kind": "pass", "config": {}})
        elif kind_of == "step":
            slug = data.get("agentSlug")
            if not slug:
                out_nodes.append({"id": nid, "kind": "pass", "config": {}})
                continue
            pin = agents.get(str(slug))
            if str(slug) not in agents:
                checks.append(Check(f"agent:{nid}", f"{label}: agent exists", False, f"No agent with slug {slug}."))
                continue
            if pin is None:
                failure = f"{slug} has no published version; publish it before a workflow can pin it."
                checks.append(Check(f"agent:{nid}", f"{label}: agent is published", False, failure))
                continue
            slugs.append(pin.slug)
            agent = definition_of(pin.id, pin.version, pin.spec).model_dump(mode="json")
            out_nodes.append({"id": nid, "kind": "agent_turn", "config": {"agent": agent}})
            checks.append(Check(f"agent:{nid}", f"{label}: pins {pin.slug} v{pin.version}", True))
        elif kind_of == "review":
            out_nodes.append({"id": nid, "kind": "human", "config": {}})
            routes = {str(e.get("sourceHandle")): (i, str(e["target"])) for i, e in outgoing(nid)}
            if "approved" in routes and "rejected" in routes:
                decide = f"{nid}__decide"
                out_nodes.append(
                    {
                        "id": decide,
                        "kind": "condition",
                        "config": {
                            "rule": "decision",
                            "approved": routes["approved"][1],
                            "rejected": routes["rejected"][1],
                        },
                    }
                )
                out_edges.append((nid, decide))
                skip_edges.update(i for i, _ in outgoing(nid))
        elif kind_of == "end":
            out_nodes.append({"id": nid, "kind": "end", "config": {}})
        elif kind_of in ("branch", "router"):
            targets = {str(e["target"]) for _, e in outgoing(nid)}
            if len(targets) <= 1:
                out_nodes.append({"id": nid, "kind": "pass", "config": {}})
                continue
            route = _route_condition(nid, label, data, outgoing(nid))
            if isinstance(route, Check):
                checks.append(route)
                continue
            out_nodes.append(route)
            skip_edges.update(i for i, _ in outgoing(nid))
        else:
            checks.append(Check(f"node:{nid}", f"{label}: node type", False, f"Unknown node type {kind_of}."))

    if len(entry) != 1:
        checks.append(Check("entry", "One trigger", False, f"The graph has {len(entry)} triggers; it needs one."))
    for i, e in enumerate(edges):
        pair = (str(e["source"]), str(e["target"]))
        if i not in skip_edges and pair not in out_edges and e.get("sourceHandle") != "timeout":
            out_edges.append(pair)
    known = {n["id"] for n in out_nodes}
    reachable: set[str] = set()
    if len(entry) == 1:
        frontier = [entry[0]]
        nexts: dict[str, set[str]] = {}
        for s, t in out_edges:
            nexts.setdefault(s, set()).add(t)
        for n in out_nodes:
            if n["kind"] == "condition":
                nexts.setdefault(n["id"], set()).update(t for _, t in condition_targets(n["config"]))
        while frontier:
            cur = frontier.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            frontier.extend(nexts.get(cur, set()))
        unreached = sorted(nid for nid in by_id if nid not in reachable and nid in known)
        if unreached:
            failure = f"Not reachable from the trigger: {', '.join(unreached)}."
            checks.append(Check("reachable", "Every step is reachable", False, failure))
        else:
            checks.append(Check("reachable", "Every step is reachable", True))
    if any(not c.passed for c in checks):
        return Compiled(None, checks, slugs)
    try:
        d = WorkflowDefinition.model_validate(
            {
                "name": name,
                "version": 0,
                "entry": entry[0],
                "nodes": out_nodes,
                "edges": [{"source": s, "target": t} for s, t in out_edges if s in known and t in known],
            }
        )
        validate(d)
    except (ValueError, InvalidDefinitionError) as e:
        return Compiled(None, [*checks, Check("definition", "Compiles to a definition", False, str(e))], slugs)
    return Compiled(d, [*checks, Check("definition", "Compiles to a definition", True)], slugs)


def _route_condition(
    nid: str, label: str, data: dict[str, Any], edges: list[tuple[int, dict[str, Any]]]
) -> dict[str, Any] | Check:
    """A branch with several routes as a `route` condition. Each outgoing edge leaves by a handle;
    `data.routes[handle]` is its comparison ({field, op, value}) and `data.defaultRoute` names the handle taken when
    none matches. The definition's validation checks the fields and operators."""
    when_by_handle: dict[str, Any] = data.get("routes") or {}
    default_handle = data.get("defaultRoute")
    routes: list[dict[str, Any]] = []
    default: str | None = None
    missing: list[str] = []
    for _, e in edges:
        handle, target = str(e.get("sourceHandle") or ""), str(e["target"])
        if handle and handle == default_handle:
            default = target
        elif isinstance(when_by_handle.get(handle), dict):
            routes.append({"when": when_by_handle[handle], "to": target})
        else:
            missing.append(handle or target)
    if default is None:
        failure = f"{label} needs a default route (data.defaultRoute) for when no comparison matches."
        return Check(f"node:{nid}", f"{label}: has a default route", False, failure)
    if missing:
        failure = f"{label}: routes {', '.join(missing)} have no comparison (data.routes)."
        return Check(f"node:{nid}", f"{label}: every route has a comparison", False, failure)
    return {"id": nid, "kind": "condition", "config": {"rule": "route", "routes": routes, "default": default}}


CONSOLE_TYPE: dict[NodeKind, str] = {"human": "review", "end": "end", "condition": "branch"}


def render_definition(d: WorkflowDefinition) -> dict[str, Any]:
    """A definition as a console graph that compiles back to the same definition (each node passes through)."""
    nodes = [
        {
            "id": n.id,
            "type": CONSOLE_TYPE.get(n.kind, "step"),
            "position": {"x": i * 270, "y": 200},
            "data": {
                "label": n.id.replace("_", " ").capitalize(),
                "description": n.kind,
                "icon": "user" if n.kind == "human" else "check" if n.kind == "end" else "brain",
                "category": "human" if n.kind == "human" else "control" if n.kind in ("end", "condition") else "ai",
                "definition": {"kind": n.kind, "config": n.config},
                **({"entry": True} if n.id == d.entry else {}),
            },
        }
        for i, n in enumerate(d.nodes)
    ]
    edges = [{"id": f"{e.source}-out-{e.target}", "source": e.source, "target": e.target} for e in d.edges]
    for n in d.nodes:
        if n.kind == "condition":
            edges += [
                {"id": f"{n.id}-{k}-{t}", "source": n.id, "target": t, "sourceHandle": k}
                for k, t in condition_targets(n.config)
            ]
    return {"nodes": nodes, "edges": edges}


# ── templates ──


def _node(nid: str, kind: str, col: int, data: dict[str, Any], y: int = 200) -> dict[str, Any]:
    base = {"label": nid.capitalize(), "description": "", "icon": "check", "category": "control"}
    return {"id": nid, "type": kind, "position": {"x": col * 270, "y": y}, "data": {**base, **data}}


def _edge(s: str, t: str, handle: str | None = None) -> dict[str, Any]:
    return {
        "id": f"{s}-{handle or 'out'}-{t}",
        "source": s,
        "target": t,
        **({"sourceHandle": handle} if handle else {}),
    }


def template_graph(template: str, trigger: str, agent_slug: str | None) -> dict[str, Any]:
    t = _node("t", "trigger", 0, {"label": trigger, "icon": "globe", "category": "trigger"})
    agent = (
        [_node("agent", "step", 1, {"label": "Agent", "icon": "brain", "category": "ai", "agentSlug": agent_slug})]
        if agent_slug
        else []
    )
    first = agent[0]["id"] if agent else None
    if template == "approval":
        review = _node("review", "review", 2, {"label": "Review", "icon": "user", "category": "human"})
        done = _node("done", "end", 3, {"label": "Approved"}, 100)
        stop = _node("stopped", "end", 3, {"label": "Rejected"}, 300)
        nodes = [t, *agent, review, done, stop]
        edges = [_edge("t", first or "review"), *([_edge(first, "review")] if first else [])]
        edges += [_edge("review", "done", "approved"), _edge("review", "stopped", "rejected")]
        return {"nodes": nodes, "edges": edges}
    done = _node("done", "end", 2 if agent else 1, {"label": "Done"})
    edges = [_edge("t", first or "done"), *([_edge(first, "done")] if first else [])]
    return {"nodes": [t, *agent, done], "edges": edges}


# ── store ──


def registry(rt: Runtime) -> WorkflowRegistry:
    return WorkflowRegistry(rt.db)


async def agent_pins(rt: Runtime) -> dict[str, PinnedAgent | None]:
    """Every agent by slug with its published pin, or None while it has no published version."""
    reg = agent_registry(rt)
    out: dict[str, PinnedAgent | None] = {}
    for r in await reg.rows():
        v = r["published_version"]
        out[r["slug"]] = (
            PinnedAgent(r["id"], r["slug"], int(v), (await reg.version(r["id"], int(v)))["spec"])
            if v is not None
            else None
        )
    return out


async def held(rt: Runtime, name: str) -> dict[str, Any] | None:
    """The registry workflow `name` when the acting team holds it; None when no team does. Another team's answers 404,
    never None: None means "a graph the registry does not hold", which the callers treat as open to the acting team."""
    row = await registry(rt).find(name)
    if row is None and await registry(rt).owner_team(name) is not None:
        raise NotFound(f"Workflow {name}")
    return row


async def thread_pin(rt: Runtime, graph: str) -> int | None:
    """The version a new thread on `graph` starts on when the caller names none: the registry pointer. Refuses a
    paused or never-published workflow; None for a graph the registry does not hold."""
    row = await held(rt, graph)
    if row is None:
        return None
    if row["status"] == "deleted":
        raise NotFound(f"Workflow {graph}")
    if row["status"] == "paused":
        raise Conflict(f"Workflow {graph} is paused; it starts no new threads.", code="workflow_paused")
    if row["published_version"] is None:
        raise ValidationFailed(f"Workflow {graph} has no published version yet.", code="not_published")
    return int(row["published_version"])


async def move_pointer(rt: Runtime, workflow_id: str, version: int) -> None:
    """Points a registry workflow at `version`; a no-op for a graph the registry does not hold."""
    if await registry(rt).find(workflow_id) is not None:
        await registry(rt).update(workflow_id, published_version=version)


async def publish(
    rt: Runtime, workflow_id: str, d: WorkflowDefinition, graph: dict[str, Any], *, note: str, by: str, review_id: str
) -> int:
    """Stores the definition as the next graph version (or the version already holding its digest), records the
    console graph beside it and points the workflow at it."""
    assert rt.graph_store is not None
    reg = registry(rt)
    previous = await reg.versions(workflow_id)
    version = await rt.graph_store.publish(workflow_id, d.model_dump(mode="json"), d.digest(), now_iso())
    changes = ["First version"] if not previous else _graph_changes(previous[0]["graph"], graph)
    await reg.add_version(
        {
            "workflow_id": workflow_id,
            "version": version,
            "graph": graph,
            "note": note,
            "changes": changes,
            "published_at": now_iso(),
            "published_by": by,
            "review_id": review_id,
        }
    )
    await reg.update(workflow_id, published_version=version, status="live", draft=None)
    return version


def _graph_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    before = {n["id"]: n for n in old.get("nodes", [])}
    after = {n["id"]: n for n in new.get("nodes", [])}
    out = [f"Added {after[i]['data'].get('label', i)}" for i in after if i not in before]
    out += [f"Removed {before[i]['data'].get('label', i)}" for i in before if i not in after]
    out += [f"Changed {after[i]['data'].get('label', i)}" for i in after if i in before and after[i] != before[i]]
    if old.get("edges") != new.get("edges") and not out:
        out.append("Changed connections")
    return out or ["No changes"]


async def load(rt: Runtime, seed_dir: Path | None) -> None:
    """Seeds a row for each published definition with none (dispute_email) and each workflow in
    `registry_workflows.json`, published at start; rows already present are left as they are."""
    assert rt.graph_store is not None
    reg = registry(rt)
    # Deleted rows count: a deleted workflow keeps its graph versions and must not come back as a seed.
    have = await reg.ids()
    names = sorted(await rt.graph_store.latest_versions())
    at = now_iso()
    for name in names:
        if name in have:
            continue
        versions = await rt.graph_store.versions(name)
        latest = versions[-1]
        d = WorkflowDefinition.model_validate(latest["definition"])
        await reg.create(
            _row(name, name.replace("_", " ").capitalize(), "Seeded definition", "Email", at, status="live")
            | {"published_version": latest["version"]}
        )
        await reg.add_version(
            {
                "workflow_id": name,
                "version": latest["version"],
                "graph": render_definition(d),
                "note": "Seeded",
                "changes": ["First version"],
                "published_at": at,
                "published_by": "seed",
                "review_id": None,
            }
        )
        have.add(name)
    path = seed_dir / "registry_workflows.json" if seed_dir else None
    if path is None or not path.exists():
        return
    pins = await agent_pins(rt)
    for seed in json.loads(path.read_text()):
        if seed["id"] in have:
            continue
        compiled = compile_graph(seed["id"], seed["graph"], pins)
        if compiled.definition is None:
            raise ValueError(f"Seed workflow {seed['id']} does not compile: {[c.failure for c in compiled.checks]}")
        await reg.create(_row(seed["id"], seed["name"], seed["description"], seed["trigger"], at))
        await publish(rt, seed["id"], compiled.definition, seed["graph"], note="Seeded", by="seed", review_id="seed")


async def follow_seed(rt: Runtime, seeded: dict[str, int]) -> None:
    """New threads of a seeded workflow start on the seed's version when it changed (a new version under a new
    digest). In dev the registry's pointer moves to it at start, so a running stack gets the change on restart.
    Outside dev a shipped seed change is not exempt from review: it is stored as the workflow's draft and opens a
    publish request, and the pointer moves only when a reviewer approves it (publish_reviews.decide). Threads under
    way keep the version they pinned, and a version a person published is never replaced by the seed."""
    assert rt.graph_store is not None
    reg = registry(rt)
    for name, version in seeded.items():
        row = await reg.find(name)
        if row is None or row["status"] == "deleted" or row["published_version"] in (None, version):
            continue
        current = next((v for v in await reg.versions(name) if v["version"] == row["published_version"]), None)
        if current is not None and current["published_by"] != "seed":
            log.info("seed_not_followed", workflow=name, published_version=row["published_version"], seed=version)
            continue
        stored = next(v for v in await rt.graph_store.versions(name) if v["version"] == version)
        d = WorkflowDefinition.model_validate(stored["definition"])
        graph = render_definition(d)
        if rt.settings.environment != "dev":
            await _seed_for_review(rt, row, version, d, graph)
            continue
        await reg.add_version(
            {
                "workflow_id": name,
                "version": version,
                "graph": graph,
                "note": "Seeded",
                "changes": ["The seed's definition changed"],
                "published_at": now_iso(),
                "published_by": "seed",
                "review_id": None,
            }
        )
        await reg.update(name, published_version=version)


SEED_REQUESTER = "seed"


async def _seed_for_review(
    rt: Runtime, row: dict[str, Any], version: int, d: WorkflowDefinition, graph: dict[str, Any]
) -> None:
    """A changed seed outside dev: the draft and one publish request for its version, as a person's save and publish
    would leave them. A version that already has a request, pending or decided, is not asked again on each restart,
    so a rejected seed change stays rejected."""
    name = str(row["id"])
    if any(int(r["version"]) == version for r in await agent_registry(rt).requests("workflow", name)):
        return
    note = "The seed's definition changed"
    info: dict[str, Any] = {
        "workflowId": name,
        "fromVersion": row["published_version"] or 0,
        "toVersion": version,
        "note": note,
        "requestedBy": SEED_REQUESTER,
        "changes": ["The seed's definition changed"],
        "validation": {"passed": 0, "total": 0, "regressions": 0, "checksFailing": 0},
        "digest": d.digest(),
        "definition": d.model_dump(mode="json"),
        "graph": graph,
        # Outside dev a seed's change waits for review; the policy decides whether it would need one (c-086).
        "reviewRequired": True,
    }
    try:
        await agent_registry(rt).open_request(
            "workflow", name, version, note=note, by=SEED_REQUESTER, body=info, approved=False
        )
    except Conflict:
        # A person's publish request is already open for this workflow: theirs is decided first.
        log.info("seed_review_deferred", workflow=name, seed=version)
        return
    # The request carries its own definition, so review works either way; the draft shows the seed's change only
    # when nobody else's draft is there to lose.
    if row.get("draft") is None or row.get("draft_saved_by") == SEED_REQUESTER:
        await registry(rt).update(name, draft=graph, draft_saved_at=now_iso(), draft_saved_by=SEED_REQUESTER)
    else:
        log.info("seed_draft_kept", workflow=name, seed=version, draft_saved_by=row.get("draft_saved_by"))
    log.info("seed_waiting_for_review", workflow=name, seed=version, published_version=row["published_version"])


def _row(wid: str, name: str, description: str, trigger: str, at: str, *, status: str = "draft") -> dict[str, Any]:
    return {
        "id": wid,
        "team_id": SEED_TEAM,
        "name": name,
        "description": description,
        "trigger": trigger,
        "status": status,
        "published_version": None,
        "draft": None,
        "draft_saved_at": None,
        "draft_saved_by": None,
        "created_at": at,
        "updated_at": at,
    }


def new_row(wid: str, name: str, trigger: str, *, team_id: str, draft: dict[str, Any], by: str) -> dict[str, Any]:
    at = now_iso()
    return _row(wid, name, "", trigger, at) | {
        "team_id": team_id,
        "draft": draft,
        "draft_saved_at": at,
        "draft_saved_by": by,
    }


# ── views ──


async def counts_24h(rt: Runtime) -> tuple[dict[str, int], dict[str, int]]:
    """Threads started in the last day, and threads waiting on a person now, by graph."""
    since = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    runs: dict[str, int] = {}
    waiting: dict[str, int] = {}
    for graph, status, created in await GraphStore(rt.db).thread_stats():
        if created >= since:
            runs[graph] = runs.get(graph, 0) + 1
        if status == "interrupted":
            waiting[graph] = waiting.get(graph, 0) + 1
    return runs, waiting


def _shape(graph: dict[str, Any]) -> tuple[list[str], int, int]:
    nodes: list[dict[str, Any]] = graph.get("nodes", [])
    datas: list[dict[str, Any]] = [n.get("data") or {} for n in nodes]
    slugs = sorted({str(d["agentSlug"]) for d in datas if d.get("agentSlug")})
    steps = sum(1 for n in nodes if n.get("type") not in ("trigger", "end"))
    defs: list[dict[str, Any]] = [d.get("definition") or {} for d in datas]
    kinds = [str(x.get("kind")) for x in defs]
    gates = sum(1 for n, k in zip(nodes, kinds, strict=True) if n.get("type") == "review" or k == "human")
    return slugs, steps, gates


def workflow_view(
    row: dict[str, Any], live: dict[str, Any] | None, pending: dict[str, Any] | None, runs: int, waiting: int
) -> dict[str, Any]:
    graph: dict[str, Any] = (live or {}).get("graph") or row["draft"] or {"nodes": [], "edges": []}
    slugs, steps, gates = _shape(graph)
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        # The owning team comes from the creator's token (c-171); the console names it from its teams list.
        "teamId": row["team_id"],
        "trigger": row["trigger"],
        "agentSlugs": slugs,
        "stepCount": steps,
        "gateCount": gates,
        "runs24h": runs,
        # A v1 thread keeps no record of reviews it has already had decided, so only open ones can be counted.
        "reviewed24h": 0,
        "openReviews": waiting,
        "status": row["status"],
        "version": row["published_version"] or 0,
        "updatedAt": row["updated_at"],
        **(
            {
                "pendingPublish": {
                    "reviewId": pending["id"],
                    "toVersion": pending["version"],
                    "requestedBy": pending["requested_by"],
                }
            }
            if pending
            else {}
        ),
        "deploymentCount": 0,
        "kind": "standard",
        "engine": "v1",
    }


RUN_STATUS = {"done": "completed", "interrupted": "waiting_review", "error": "failed", "lease_lost": "failed"}
STEP_KIND = {"pass": "action", "agent_turn": "agent", "human": "review", "end": "end", "tool": "tool"}


def _ms(a: str, b: str) -> int:
    try:
        return max(0, int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() * 1000))
    except ValueError:
        return 0


async def run_rows(rt: Runtime, workflow_id: str) -> list[dict[str, Any]]:
    """The workflow's threads as the console's WorkflowRun, steps from each thread's run journal."""
    assert rt.graph_store is not None
    store = rt.graph_store
    kinds: dict[int, dict[str, str]] = {}
    for v in await store.versions(workflow_id):
        kinds[int(v["version"])] = {n["id"]: n["kind"] for n in v["definition"]["nodes"]}
    out: list[dict[str, Any]] = []
    for t in await store.threads(workflow_id):
        status = RUN_STATUS.get(str(t["status"]), "running")
        node_kinds = kinds.get(int(t["version"] or 0), {})
        steps: list[dict[str, Any]] = []
        for run in await store.runs(t["id"]):
            for e in run["events"]:
                if e.get("event") == "node_start" and e.get("node") in node_kinds:
                    nid = str(e["node"])
                    steps.append(
                        {
                            "nodeId": nid,
                            "label": nid.replace("_", " ").capitalize(),
                            "kind": STEP_KIND.get(node_kinds[nid], "action"),
                            "status": "done",
                            "durationMs": 0,
                        }
                    )
        if steps and status == "waiting_review":
            steps[-1]["status"] = "waiting"
        meta: dict[str, Any] = t["meta"] or {}
        out.append(
            {
                "id": t["id"],
                "workflowId": workflow_id,
                "version": t["version"] or 0,
                "subject": str(meta.get("subject") or f"Run {t['id']}"),
                "status": status,
                "startedAt": t["created_at"],
                "durationMs": _ms(t["created_at"], t["updated_at"]),
                **({"reviewId": t["id"]} if status == "waiting_review" else {}),
                "steps": steps,
            }
        )
    return out
