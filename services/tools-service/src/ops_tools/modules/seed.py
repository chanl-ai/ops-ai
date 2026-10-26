"""Turns the console's tool-module seed (exported to `tests/fixtures/tool_modules.json`) into registry aggregates, so a
dev tools-service serves the same modules the console's mock shows. Times in the seed are relative (days ago, days
until expiry) and become timestamps against `now`.

The rules mirror the mock's `fromSeed` (apps/console/src/lib/api/mock/tool-modules/index.ts): an operation's access,
description and traffic come from the console's tool record when one exists, writes need approval unless the seed
says otherwise, and an operation two people approve always does. A version waiting for review names its request in
agents-service's Reviews.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from ops_store.team_scope import acting_as

from ..connections.records import seed_rows
from ..store.connections import ConnectionStore
from ..store.egress import EgressStore
from ..store.modules import Aggregate, ModuleStore, StaleModuleError

DOCUMENT_SERVICE = {
    "displayName": "Document service",
    "name": "document-service",
    "type": "http",
    "description": "Fetches signed loan documents for the lending inbox.",
    "ownerTeam": "Lending Ops",
}
REQUESTERS = ("Maya Okafor", "Priya Shah", "Anika Singh")
# Workflow tools the agents catalogue does not list but the Runtime runs locally; send_reply emails a customer.
WORKFLOW_TOOLS = ("send_reply", "open_case", "send_acknowledgement")
# The mail sends: a reply waits for a person; an acknowledgement to the sender of a message leaves at once (c-532).
SENDS = {
    "send_reply": ("Email a reply to a customer.", True),
    "send_acknowledgement": ("Email an automatic acknowledgement to the sender of a message; no approval.", False),
}
# Tools of the platform itself, run locally in every tenant's Runtime module, and the one declaration of their access
# and approval (registry.WORKFLOW_TOOLS reads it). open_case opens a case in the caller's team (c-219): a write, but
# one that changes only the team's own case list and closes nothing, so it runs without approval unless the team's
# toolWritesNeedApproval policy is on.
PLATFORM_TOOLS: list[dict[str, Any]] = [
    {
        "name": "open_case",
        "description": "Open a case for a customer issue in your team; returns its id. Calling again with the same "
        "call key returns the same case.",
        "access": "write",
        "requires_approval": False,
        "input_schema": {
            "type": "object",
            "required": ["subject"],
            "properties": {
                "subject": {"type": "string", "description": "What the issue is, in a line"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                "customerId": {"type": "string", "description": "The customer's id in the bank's system"},
                "customerName": {"type": "string"},
            },
        },
    },
    # Applies a tool access request's decision (c-257). Only the tool_access_request system workflow calls it, after
    # its review: the gateway refuses it from any other workflow, and it is not an operation an agent can be granted.
    {
        "name": "apply_tool_access",
        "description": "Apply a tool access request's decision to the module's grant.",
        "access": "write",
        "requires_approval": True,
        "system": True,
        "input_schema": {
            "type": "object",
            "required": ["moduleId", "approvalId", "decision"],
            "properties": {
                "moduleId": {"type": "string"},
                "approvalId": {"type": "string"},
                "decision": {"type": "string", "enum": ["approved", "rejected"]},
                "reason": {"type": "string", "description": "Why it was rejected"},
            },
        },
    },
]
# What the Runtime sends for send_reply (ops_agents.activities.gateway); the gateway validates against it.
SEND_REPLY_INPUT = [
    {"name": "to", "type": "string", "required": True},
    {"name": "subject", "type": "string", "required": True},
    {"name": "body", "type": "string", "required": True},
    # The address of the team's mailbox the reply leaves from; without it the process-wide sender sends.
    {"name": "mailbox", "type": "string", "required": False},
]
RUNTIME_MODULE = "mod_runtime_demo"
# The platform's workflow tools in an install the dev seed did not write (ensure_platform_tools).
PLATFORM_MODULE = "mod_platform_tools"


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
    *, module_id: str, tenant_id: str, team_id: str | None, owner: str, me: str, at: datetime, input: dict[str, Any]
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
        "template_id": None,
        "protection": None,
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
        "approvals": [],
    }


def runtime_module(
    catalog: list[dict[str, Any]], *, tenant_id: str, team_id: str | None, me: str, at: datetime
) -> Aggregate:
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
            # Declared on the tool; a write that declares nothing waits for approval.
            "requires_approval": t["access"] != "read" and t.get("requires_approval") is not False,
            "approvers": 1,
            "amount_max": None,
            "stub": {"ok": True},
        }
        for i, t in enumerate(catalog)
    ]
    version = {**m["versions"][0], "id": f"{RUNTIME_MODULE}_v1.0.0", "version": "1.0.0", "major": 1}
    version.update(status="published", published_at=at, note="The Runtime's demo tools")
    return {
        **m,
        "status": "published",
        "description": "Tools the Runtime runs in process for its demo agents and workflows.",
        "version": "1.0.0",
        "operations": ops,
        "versions": [version],
    }


def platform_module(names: list[str], *, tenant_id: str, at: datetime) -> Aggregate:
    """The platform tools `names` (of WORKFLOW_TOOLS), as one published module the gateway runs locally. No team owns
    it (c-433): every team reads and calls it, and a held write is decided by the calling run's team."""
    declared = {str(t["name"]): t for t in PLATFORM_TOOLS}
    m = blank(
        module_id=PLATFORM_MODULE,
        tenant_id=tenant_id,
        team_id=None,
        owner="Platform",
        me="tools-service",
        at=at,
        input={"displayName": "Platform tools", "name": "platform-tools", "type": "code"},
    )
    ops: list[dict[str, Any]] = []
    for i, name in enumerate(names):
        if name in SENDS:
            (description, approval), access, fields = SENDS[name], "write", SEND_REPLY_INPUT
        else:
            t = declared[name]
            description, access = str(t["description"]), str(t["access"])
            approval, fields = bool(t["requires_approval"]), fields_of(t["input_schema"])
        ops.append(
            {
                "id": f"{PLATFORM_MODULE}_op{i + 1}",
                "tool_id": f"tl_{name}",
                "name": name,
                "description": description,
                "access": access,
                "enabled": True,
                "executor": "local",
                "method": None,
                "path": None,
                "headers": [],
                "body": None,
                "input": fields,
                "masked_output": [],
                "binding": None,
                "rate_limit_per_min": 60,
                "requires_approval": approval,
                "approvers": 1,
                "amount_max": None,
                "stub": {"ok": True},
            }
        )
    version = {**m["versions"][0], "id": f"{PLATFORM_MODULE}_v1.0.0", "version": "1.0.0", "major": 1}
    version.update(status="published", published_at=at, note="The platform's workflow tools")
    return {
        **m,
        "status": "published",
        "description": "Workflow tools run in process: send_reply emails a reply, send_acknowledgement thanks a "
        "sender at once, open_case opens a case.",
        "version": "1.0.0",
        "operations": ops,
        "versions": [version],
    }


async def ensure_platform_tools(store: ModuleStore, *, tenant_id: str, at: datetime) -> Literal["present", "written"]:
    """Writes the Platform tools module for the platform tools no module of the tenant holds, so a workflow's reply
    resolves in every install and not only where the dev seed wrote its mail module. A tool declared after the module
    was written is added to that copy (c-509), so send_acknowledgement reaches a team that already has one. It is a
    workspace-level record: no team owns it (c-433), and every team reads and calls it."""
    taken = await store.names_taken(tenant_id, list(WORKFLOW_TOOLS))
    missing = [n for n in WORKFLOW_TOOLS if n not in taken]
    if not missing:
        return "present"
    existing = await store.get_any(tenant_id, PLATFORM_MODULE)
    if existing is None:
        module = platform_module(missing, tenant_id=tenant_id, at=at)
        return "written" if await store.insert_if_missing(module) else "present"
    added = [
        {**o, "id": f"{existing['id']}_{o['name']}"}
        for o in platform_module(missing, tenant_id=tenant_id, at=at)["operations"]
    ]
    baseline = existing.get("baseline")
    try:
        await store.put(
            {
                **existing,
                "operations": [*existing["operations"], *added],
                "baseline": None if baseline is None else [*baseline, *added],
            },
            expected_revision=existing["revision"],
            seeded=existing["revision"] == 0,
        )
    except StaleModuleError:
        return "present"
    except Exception as e:
        # Another first lookup inserted the same operation name (store.put raises sqlalchemy IntegrityError).
        if type(e).__name__ != "IntegrityError":
            raise
        return "present"
    return "written"


def aggregates(
    seed: dict[str, Any], *, tenant_id: str, now: datetime, catalog: list[dict[str, Any]] | None = None
) -> list[Aggregate]:
    """`catalog` is the agents catalogue's tools.json: those tools run locally, and the ones no console module holds
    join one Runtime module."""
    tools = {t["name"]: t for t in seed["tools"]}
    local = {t["name"] for t in catalog or []} | set(WORKFLOW_TOOLS)
    # A tool the Runtime runs locally takes the Runtime's input, which can differ from the console seed's picture of
    # the same operation; the gateway validates calls against what will actually run.
    runtime_input = {
        t["name"]: fields_of(t.get("input_schema") or {}) for t in [*(catalog or []), *PLATFORM_TOOLS]
    } | dict.fromkeys(SENDS, SEND_REPLY_INPUT)
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
                    "requires_approval": access == "write" and o.get("requiresApproval") is not False,
                    "approvers": int(base.get("approvers") or 1),
                    # Who approves a write when not the module's own team (Fraud Operations decides a wire hold).
                    **({"approver_team": base["approverTeam"]} if base.get("approverTeam") else {}),
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
        # A pending review is a publish request in agents-service's Reviews (c-163); the start-up hand-over opens it
        # there on the publisher's behalf and the version takes the id Reviews names (c-222).
        if versions[-1]["status"] == "in_review":
            mj = major_of(last["version"])
            versions[-1].update(review_id=f"TMP-{s['id']}_rev{mj}", requested_at=ago(last["daysAgo"] + 3))
        elif s.get("findings"):
            versions[-1].update(reviewer=s.get("reviewer"), finding="; ".join(s["findings"]))
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
    rest = [t for t in [*(catalog or []), *PLATFORM_TOOLS] if t["name"] not in held and not t.get("system")]
    if rest:
        # The catalogue's runtime tools are the platform's, like the platform tools module: no team owns them (c-433).
        out.append(runtime_module(rest, tenant_id=tenant_id, team_id=None, me=seed["currentUser"], at=ago(30)))
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
    0) are replaced so a changed seed reaches an existing dev database, and edited ones are left alone; an unedited
    Runtime module the seed no longer writes is removed. Returns how many it added."""
    added = 0
    mods = aggregates(seed, tenant_id=tenant_id, now=now, catalog=catalog)
    # The seed's integrations are connection records with the same ids (c-330), owned by its all-scope team; one
    # already there is left as it is.
    connections = ConnectionStore(store.engine)
    everyone = next((t["id"] for t in seed.get("teams", []) if t["scope"] == "all"), "team_ops")
    for row in seed_rows(seed, tenant_id, everyone, now):
        await connections.create(row, actor="dev seed", at=now)
    # A module may only name listed hosts, so the seed lists the hosts its modules call first.
    egress = EgressStore(store.engine)
    for host in dict.fromkeys(h for m in mods for h in m["egress_hosts"]):
        await egress.add(tenant_id, "host", host, actor="dev seed", note="called by a seeded module", at=now)
    for agg in mods:
        # Each module is written in its own team so a leftover acting team cannot hide it or raise NoTenantError.
        with acting_as(agg["team_id"]):
            stored = await store.get(tenant_id, agg["id"])
            if stored is None:
                await store.put(agg, expected_revision=None, seeded=True)
                added += 1
            elif stored["revision"] == 0:
                await store.put(agg, expected_revision=0, seeded=True)
    # A seed without the agents catalogue holds no Runtime module; one an earlier seed wrote and nobody edited goes.
    if RUNTIME_MODULE not in {m["id"] for m in mods}:
        with acting_as(None):
            stale = await store.get(tenant_id, RUNTIME_MODULE)
            if stale is not None and stale["revision"] == 0:
                await store.delete(tenant_id, RUNTIME_MODULE)
    return added
