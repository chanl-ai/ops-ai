"""Turns the console's tool-module seed (exported to `tests/fixtures/tool_modules.json`) into registry aggregates, so a
dev tools-service serves the same modules the console's mock shows. Times in the seed are relative (days ago, days
until expiry) and become timestamps against `now`.

The rules mirror the mock's `fromSeed` (apps/console/src/lib/api/mock/tool-modules/index.ts): an operation's access,
description and traffic come from the console's tool record when one exists, writes need approval unless the seed
says otherwise, money movement always does, and each major version has one security review.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..store.egress import EgressStore
from ..store.modules import Aggregate, ModuleStore

DOCUMENT_SERVICE = {
    "displayName": "Document service",
    "name": "document-service",
    "type": "http",
    "description": "Fetches signed loan documents for the lending inbox.",
    "ownerTeam": "Lending Ops",
}
REQUESTERS = ("Maya Okafor", "Priya Shah", "Anika Singh")
# Workflow tools the agents catalogue does not list but the Runtime runs locally; send_reply emails a customer.
WORKFLOW_TOOLS = ("send_reply",)
# What the Runtime sends for send_reply (ops_agents.activities.gateway); the gateway validates against it.
SEND_REPLY_INPUT = [
    {"name": "to", "type": "string", "required": True},
    {"name": "subject", "type": "string", "required": True},
    {"name": "body", "type": "string", "required": True},
]
RUNTIME_MODULE = "mod_runtime_demo"


def fields_of(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """A JSON Schema object's top-level properties as the console's SchemaField list."""
    required: set[str] = set(schema.get("required") or [])
    props: dict[str, dict[str, Any]] = schema.get("properties") or {}
    out: list[dict[str, Any]] = []
    for name, p in props.items():
        field: dict[str, Any] = {"name": name, "type": p.get("type", "string"), "required": name in required}
        if p.get("description"):
            field["description"] = p["description"]
        if p.get("enum"):
            field["enum"] = p["enum"]
        out.append(field)
    return out


def major_of(version: str) -> int:
    return int(version.split(".", maxsplit=1)[0])


def team_of(owner_group: str | None, teams: list[dict[str, Any]]) -> str:
    """The team whose owner groups include `owner_group`; an owner outside every team falls to the all-scope team."""
    for t in teams:
        if t["scope"] == "owned" and owner_group in t["ownerGroups"]:
            return t["id"]
    return next(t["id"] for t in teams if t["scope"] == "all")


def blank(
    *, module_id: str, tenant_id: str, team_id: str, owner: str, me: str, at: datetime, input: dict[str, Any]
) -> Aggregate:
    """A draft with a name and a type and nothing else; operations, connection and settings are added on its page."""
    display = input["displayName"].strip()
    return {
        "id": module_id,
        "tenant_id": tenant_id,
        "team_id": team_id,
        "name": input["name"],
        "display_name": display,
        "system": display,
        "description": (input.get("description") or "").strip(),
        "type": input["type"],
        "status": "draft",
        "owner_team": owner,
        "owner_contacts": [me],
        "endpoint": "",
        "auth": {"kind": "none"},
        "timeout_ms": 8000,
        "egress_hosts": [],
        "data_classification": "confidential",
        "catalog_id": None,
        "connection_id": None,
        "reachable": True,
        "drift": False,
        "version": "0.1.0",
        "pending": [],
        "baseline": None,
        "created_at": at,
        "updated_at": at,
        "operations": [],
        "versions": [
            {
                "id": f"{module_id}_v0.1.0",
                "version": "0.1.0",
                "major": 0,
                "status": "draft",
                "published_at": None,
                "published_by": me,
                "note": "First version",
                "changes": [],
                "pinned_by": [],
                "reachability": [],
            }
        ],
        "reviews": [],
        "approvals": [],
    }


def runtime_module(catalog: list[dict[str, Any]], *, tenant_id: str, team_id: str, me: str, at: datetime) -> Aggregate:
    """The agents catalogue's demo tools that no console module holds, as one published module the gateway runs
    locally, so every tool a call can name is in the registry."""
    m = blank(
        module_id=RUNTIME_MODULE,
        tenant_id=tenant_id,
        team_id=team_id,
        owner="Platform",
        me=me,
        at=at,
        input={"displayName": "Runtime demo tools", "name": "runtime-demo-tools", "type": "code"},
    )
    ops = [
        {
            "id": f"{RUNTIME_MODULE}_op{i + 1}",
            "tool_id": f"tl_{t['name']}",
            "name": t["name"],
            "description": t["description"],
            "access": t["access"],
            "enabled": True,
            "executor": "local",
            "method": None,
            "path": None,
            "headers": [],
            "body": None,
            "input": fields_of(t.get("input_schema") or {}),
            "masked_output": [],
            "binding": None,
            "rate_limit_per_min": 60,
            "requires_approval": t["access"] != "read",
            "amount_max": None,
            "stub": {"ok": True},
        }
        for i, t in enumerate(catalog)
    ]
    version = {**m["versions"][0], "id": f"{RUNTIME_MODULE}_v1.0.0", "version": "1.0.0", "major": 1}
    version.update(status="published", published_at=at, note="The Runtime's demo tools")
    review: dict[str, Any] = {
        "id": f"{RUNTIME_MODULE}_rev1",
        "major": 1,
        "version": "1.0.0",
        "decision": "approved",
        "requested_by": me,
        "requested_at": at,
        "reviewer": me,
        "decided_at": at,
        "findings": [],
        "note": None,
    }
    return {
        **m,
        "status": "published",
        "description": "Tools the Runtime runs in process for its demo agents and workflows.",
        "version": "1.0.0",
        "operations": ops,
        "versions": [version],
        "reviews": [review],
    }


def aggregates(
    seed: dict[str, Any], *, tenant_id: str, now: datetime, catalog: list[dict[str, Any]] | None = None
) -> list[Aggregate]:
    """`catalog` is the agents catalogue's tools.json: those tools run locally, and the ones no console module holds
    join one Runtime module."""
    tools = {t["name"]: t for t in seed["tools"]}
    local = {t["name"] for t in catalog or []} | set(WORKFLOW_TOOLS)
    # A tool the Runtime runs locally takes the Runtime's input, which can differ from the console seed's picture of
    # the same operation; the gateway validates calls against what will actually run.
    runtime_input = {t["name"]: fields_of(t.get("input_schema") or {}) for t in catalog or []} | {
        "send_reply": SEND_REPLY_INPUT
    }
    # Workflows are agents-service's; the seed keeps each approval's workflow name, and a test fixture may list them.
    workflows = {w["id"]: w["name"] for w in seed.get("workflows", [])}
    teams: list[dict[str, Any]] = seed["teams"]

    def ago(days: float) -> datetime:
        return now - timedelta(days=days)

    out: list[Aggregate] = []
    for s in seed["modules"]:
        status = s.get("status") or "published"
        last = s["versions"][-1]
        ops: list[dict[str, Any]] = []
        for i, o in enumerate(s["operations"]):
            base = tools.get(o["name"]) or o.get("tool") or {"description": o["name"], "access": "read"}
            access = base["access"]
            money = access == "money_movement"
            ops.append(
                {
                    "id": f"{s['id']}_op{i + 1}",
                    "tool_id": f"tl_{o['name']}",
                    "name": o["name"],
                    "description": base["description"],
                    "access": access,
                    "enabled": base.get("enabled", True),
                    # Seeded systems have no reachable upstream, so their operations answer from the stub.
                    "executor": "local" if o["name"] in local else "stub",
                    "method": o.get("method"),
                    "path": o.get("path"),
                    "headers": [],
                    "body": None,
                    "input": runtime_input[o["name"]] if o["name"] in local else o["input"],
                    "masked_output": o.get("masked") or [],
                    "binding": o.get("binding"),
                    "rate_limit_per_min": o.get("rate") or 60,
                    "requires_approval": money or (access == "write" and o.get("requiresApproval") is not False),
                    "amount_max": o.get("amountMax"),
                    "stub": o.get("stub") or {"ok": True},
                }
            )
        versions: list[dict[str, Any]] = []
        for i, v in enumerate(s["versions"]):
            is_last = i == len(s["versions"]) - 1
            in_review = is_last and status == "in_review"
            pinned: list[str] = v.get("pinnedBy") or []
            versions.append(
                {
                    "id": f"{s['id']}_v{v['version']}",
                    "version": v["version"],
                    "major": major_of(v["version"]),
                    "status": ("in_review" if in_review else "published") if is_last else "deprecated",
                    "published_at": None if in_review else ago(v["daysAgo"]),
                    "published_by": v["by"],
                    "note": v["note"],
                    "changes": v["changes"],
                    "pinned_by": [{"id": w, "name": workflows.get(w, w)} for w in pinned],
                    "reachability": [
                        {
                            "environment": "production",
                            "ok": s.get("reachable") is not False,
                            "checkedAt": ago(0.01).isoformat(),
                        },
                        {"environment": "test", "ok": True, "checkedAt": ago(0.02).isoformat()},
                    ]
                    if is_last
                    else [{"environment": "production", "ok": True, "checkedAt": ago(v["daysAgo"]).isoformat()}],
                }
            )
        reviews: list[dict[str, Any]] = []
        for mj in dict.fromkeys(major_of(v["version"]) for v in s["versions"]):
            first = next(v for v in s["versions"] if major_of(v["version"]) == mj)
            current = mj == major_of(last["version"])
            pending = current and bool(s.get("reviewPending"))
            reviews.append(
                {
                    "id": f"{s['id']}_rev{mj}",
                    "major": mj,
                    "version": first["version"],
                    "decision": "pending" if pending else "approved",
                    "requested_by": first["by"],
                    "requested_at": ago(first["daysAgo"] + 3),
                    "reviewer": None if pending else s.get("reviewer"),
                    "decided_at": None if pending else ago(first["daysAgo"] + 1),
                    "findings": (s.get("findings") or [])
                    if current
                    else ["Reviewed; superseded by the next major version"],
                    "note": None,
                }
            )
        approvals: list[dict[str, Any]] = []
        for i, a in enumerate(s["approvals"]):
            requested = a.get("status") == "requested"
            age = a.get("ageDays") if a.get("ageDays") is not None else 30 + ((i * 37) % 120)
            approvals.append(
                {
                    "id": f"{s['id']}_apr{i + 1}",
                    "workflow_id": a["workflowId"],
                    "workflow_name": a.get("workflowName") or workflows.get(a["workflowId"], a["workflowId"]),
                    "workflow_team_id": a.get("workflowTeamId"),
                    "environment": a.get("environment") or "production",
                    "major": major_of(last["version"]),
                    "operations": a["operations"],
                    "constraints": a.get("constraints"),
                    "requested_by": a.get("requestedBy") or REQUESTERS[i % 3],
                    "justification": a["justification"],
                    "requested_at": ago(age + 1),
                    "decided_by": None if requested else a.get("decidedBy"),
                    "decided_at": None if requested else ago(age),
                    "status": a.get("status") or "approved",
                    "expires_at": now + timedelta(days=a["expiresIn"]) if a.get("expiresIn") is not None else None,
                    "reason": None,
                }
            )
        out.append(
            {
                "id": s["id"],
                "tenant_id": tenant_id,
                "team_id": team_of(s["ownerTeam"], teams),
                "name": s["name"],
                "display_name": s["displayName"],
                "system": s["system"],
                "description": s["description"],
                "type": s["type"],
                "status": status,
                "owner_team": s["ownerTeam"],
                "owner_contacts": s["ownerContacts"],
                "endpoint": s["endpoint"],
                "auth": {"kind": s["auth"], **({"header": s["authHeader"]} if s.get("authHeader") else {})},
                "timeout_ms": s["timeoutMs"],
                "egress_hosts": s["egressHosts"],
                "data_classification": s["dataClassification"],
                "catalog_id": s.get("catalogId"),
                "connection_id": seed["moduleConnection"].get(s["id"]),
                "reachable": s.get("reachable") is not False,
                "drift": bool(s.get("drift")),
                "version": last["version"],
                "pending": [],
                "baseline": None,
                "created_at": ago(s["versions"][0]["daysAgo"]),
                "updated_at": ago(last["daysAgo"]),
                "operations": ops,
                "versions": versions,
                "reviews": reviews,
                "approvals": approvals,
            }
        )
    owner = DOCUMENT_SERVICE["ownerTeam"]
    out.append(
        blank(
            module_id="mod_document_service",
            tenant_id=tenant_id,
            team_id=team_of(owner, teams),
            owner=owner,
            me=seed["currentUser"],
            at=ago(1),
            input=DOCUMENT_SERVICE,
        )
    )
    held = {o["name"] for m in out for o in m["operations"]}
    rest = [t for t in catalog or [] if t["name"] not in held]
    if rest:
        platform = team_of("Platform", teams)
        out.append(runtime_module(rest, tenant_id=tenant_id, team_id=platform, me=seed["currentUser"], at=ago(30)))
    return out


async def load(
    store: ModuleStore,
    seed: dict[str, Any],
    *,
    tenant_id: str,
    now: datetime,
    catalog: list[dict[str, Any]] | None = None,
) -> int:
    """Writes the seeded modules: missing ones are added, ones nobody has edited since the seed wrote them (revision
    0) are replaced so a changed seed reaches an existing dev database, and edited ones are left alone. Returns how
    many it added."""
    added = 0
    mods = aggregates(seed, tenant_id=tenant_id, now=now, catalog=catalog)
    # A module may only name listed hosts, so the seed lists the hosts its modules call first.
    egress = EgressStore(store.engine)
    for host in dict.fromkeys(h for m in mods for h in m["egress_hosts"]):
        await egress.add(tenant_id, "host", host, actor="dev seed", note="called by a seeded module", at=now)
    for agg in mods:
        stored = await store.get(tenant_id, agg["id"])
        if stored is None:
            await store.put(agg, expected_revision=None, seeded=True)
            added += 1
        elif stored["revision"] == 0:
            await store.put(agg, expected_revision=0, seeded=True)
    return added
