"""The tool-module registry's rules: the console's tool-modules contract, served from the database.

Each rule is ported from the console's mock (apps/console/src/lib/api/mock/tool-modules/index.ts), which remains the
specification: approval state, views and facets, staged changes and major versus minor publishes, security reviews,
workflow approvals with expiry that the requester never decides, the refusal of literal credentials, and the test
console's deny reasons. A method reads the module aggregate, changes it, and writes it back against the revision it
read, so two concurrent edits cannot overwrite each other.

Not here yet: discovery and import from OpenAPI or MCP (c-008), auditing to platform-service, and granting approved
operations to a workflow's agent (agents-service owns grants).
"""

from __future__ import annotations

import copy
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import yaml

from ops_access import Access, require_provisioner
from ops_identity import Principal
from ops_service_kit.errors import (
    ApiError,
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    Unprocessable,
    ValidationFailed,
)
from ops_service_kit.http import paged
from ops_service_kit.ids import new_id

from .. import mcp, transform
from ..auth import Authenticator, AuthFailed, may_use
from ..auth.kinds import TEST
from ..connections.records import module_auth, ref_of, status_of
from ..egress import EgressDenied, EgressPolicy, egress_client, for_tenant
from ..executor import HttpExecutor, McpExecutor, Trial, masked, secret_names, with_defaults
from ..limits import amount_refusal
from ..mocks import MockAnswers
from ..registry import approval_policy
from ..secrets import SecretResolver, scrub
from ..store.calls import CallLog
from ..store.connections import ConnectionStore
from ..store.mocks import MockStore
from ..store.modules import CALL_SHAPE, REVIEWED, Aggregate, HostNotAllowedError, ModuleStore, StaleModuleError
from . import openapi
from .directory import Directory, Team
from .executions import call_row
from .policy import PublishPolicy, RequesterMayDecide, ToolsMode
from .review_events import ACCESS_REQUESTED, access_event
from .reviews import ReviewOpener
from .seed import blank, major_of
from .workflows import StaticWorkflows, WorkflowDirectory

Traffic = dict[tuple[str, str | None], dict[str, Any]]
NO_TRAFFIC: dict[str, Any] = {"calls": 0, "errors": 0, "p95Ms": 0}


def _rates(t: dict[str, Any]) -> dict[str, Any]:
    return {"calls24h": t["calls"], "errorRate": t["errors"] / t["calls"] if t["calls"] else 0, "p95Ms": t["p95Ms"]}


# Short enough that an approval granted for 30 days (the test default) is not expiring the day it is granted.
EXPIRING = timedelta(days=7)
GRANT_VIEWS = ("active", "expiring", "requested", "expired", "ended", "all")
FAILING_RATE = 0.02
ACCESS_ORDER = ("read", "write")
WRITES = {"write"}
# The case id of a run context with no case: the builder types the bound values (c-039).
# The run context of the module's own team trying it, with no workflow and no case (c-048 T008).
OWNER_CONTEXT = "owner"
SAMPLE_CASE = "sample"
STATUS_ORDER = {"requested": 0, "approved": 1, "expired": 2, "rejected": 3, "revoked": 4}
CREDENTIAL_HEADER = re.compile(r"^(authorization|x-api-key|cookie)$", re.IGNORECASE)
SECRET_REFERENCE = re.compile(r"^\{\{[A-Z][A-Z0-9_]*\}\}$")
OPERATION_NAME = re.compile(r"^[a-z][a-z0-9_]{2,}$")
# An argument placeholder in a path; the inner braces of a `{{SECRET}}` reference are not one, so a secret the URL
# reads never becomes an input an agent fills.
URL_VAR = re.compile(r"(?<!\{)\{([a-zA-Z0-9_]+)\}(?!\})")
FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
DEFAULT_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}
BODY_VAR = re.compile(r"\{\{\s*([a-z][a-zA-Z0-9_]*)\s*\}\}")

DENY_TEXT = {
    "no_approval": "This workflow has no approval for the module.",
    "approval_expired": "The workflow's approval for this module has expired.",
    "operation_not_approved": "The workflow's approval does not include this operation.",
    "operation_hidden": "The operation is hidden in this module.",
    "subject_unbound": "The case has no bound value for this record, so the call cannot name one.",
    "subject_mismatch": "The input names a different record from the one bound to the case.",
    "constraint": "The amount is above the operation's limit.",
    "approval_token_missing": "This call needs an approval token bound to this input. Simulate the approval to "
    "continue the test, or run it against the stub.",
    "module_not_published": "The module is not published, so only the stub can be called.",
}


class NotYetAvailable(ApiError):
    status = 501
    code = "not_implemented"


class UpstreamUnavailable(ApiError):
    status = 502
    code = "upstream_unavailable"


# A spec larger than this is refused rather than parsed.
MAX_SPEC_BYTES = 2_000_000
# A mock response is a sample answer, not a dataset.
MAX_STUB_BYTES = 64_000


@dataclass(frozen=True)
class Caller:
    """Who is asking and in which team, from ops_identity's principal. `roles` maps team id to role; `verified` is
    False only for the dev-header principal, which carries no roles, so role rules apply to anyone with a token."""

    tenant_id: str
    name: str
    team: Team
    roles: dict[str, str] = field(default_factory=dict[str, str])
    verified: bool = False
    # The caller's role in the team the request acts in (the token's team, before any fallback to an all-scope team).
    team_role: str | None = None
    # The verified principal, which `ops_access.can` decides on (c-149); None for a caller made in code (the seed).
    principal: Principal | None = None
    # The identity headers the caller sent, lower-cased, passed through when tools-service asks agents-service on their
    # behalf (the publish policy), so agents-service decides what they may read.
    credentials: dict[str, str] = field(default_factory=dict[str, str])


def _can(
    who: Caller,
    area: str,
    action: str,
    *,
    what: str,
    security_team: str,
    code: str = "role_required",
    protection: str | None = None,
    requested_by: tuple[str | None, ...] = (),
) -> None:
    """`ops_access.can` for a tools-service caller (c-149): the grid decides, in the team the request acts in, or in the
    Security team for the actions held there. A caller with no principal (the seed) acts as the system. `requested_by`
    is refused only while the tenant's requesterMayDecide policy is off (c-186)."""
    if who.principal is None:
        return
    Access(security_team=security_team).can(
        who.principal, area, action, what=what, code=code, protection=protection, requested_by=requested_by
    )


def _provisioned(who: Caller, i: dict[str, Any]) -> dict[str, Any]:
    """The template fields a create or patch carries (c-180), refused with `provisioner_only` unless the caller is a
    service token holding `tools:provision`: a person setting them could take a template's slot or lock others out."""
    fields = {k: i[k] for k in ("template_id", "protection") if i.get(k) is not None}
    if fields and who.principal is not None:
        require_provisioner(who.principal, "tools")
    return fields


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _code_settings(c: dict[str, Any]) -> dict[str, Any]:
    """A code operation's settings as stored and sent to runner-service (c-531), from CodeSettingsIn's dump."""
    limits = cast(dict[str, Any], c.get("limits") or {})
    return {
        "source": c["source"],
        "entry": c.get("entry") or "main",
        "bindings": list(dict.fromkeys(c.get("bindings") or [])),
        "secrets": list(dict.fromkeys(c.get("secrets") or [])),
        "limits": {
            "memoryMb": limits.get("memory_mb", 256),
            "timeS": limits.get("time_s", 10),
            "calls": limits.get("calls", 20),
        },
    }


def _code_operation(f: dict[str, Any]) -> dict[str, Any]:
    """A new code operation from CodeOperationIn's dump."""
    return {
        "name": f["name"],
        "description": f["description"],
        "access": f["access"],
        "group": "functions",
        "input": f["input"],
        "executor": "code",
        "code": _code_settings(f["code"]),
    }


def _kebab(s: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))


def _not_allowed(host: str) -> Unprocessable:
    return Unprocessable(
        f"{host} is not on the egress allow-list. An admin adds it under Egress before a module can call it.",
        code="egress_host_not_allowed",
    )


def _sample_field(name: str) -> dict[str, Any]:
    return {"name": name, "type": "string", "required": True}


def _workflow_names(mods: list[Aggregate]) -> dict[str, str]:
    """Each workflow's name as its approvals recorded it from agents-service, for the call log."""
    return {a["workflow_id"]: a["workflow_name"] for m in mods for a in m["approvals"]}


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _reviewed(op: dict[str, Any], key: str) -> Any:
    """The part of a reviewed field Security reviews. For the input that is each field's name, type, whether it is
    required, its allowed values and its default (a default is sent for the agent on reads, so it changes what a call
    does); a description or example changes nothing a call sends."""
    if key != "input":
        return _plain(op.get(key))
    return sorted(
        (f["name"], f["type"], bool(f.get("required")), list(f.get("enum") or []), json.dumps(f.get("default")))
        for f in cast(list[dict[str, Any]], op.get("input") or [])
    )


def _differs_from_published(m: Aggregate) -> bool:
    """Whether the operations about to go live differ from the published ones (the baseline) in anything Security
    reviews. Publish decides major from this, never from the edit history alone, so a change reaches calls without
    review by no route: an edit, an import, or a declined version's edits left in place."""
    baseline = cast(list[dict[str, Any]] | None, m.get("baseline"))
    if baseline is None:
        return False
    published = {o["id"]: o for o in baseline}
    for o in m["operations"]:
        before = published.get(o["id"])
        if before is None:
            return True
        if any(_reviewed(o, k) != _reviewed(before, k) for k in REVIEWED if k in before):
            return True
    return False


def _given(source: dict[str, Any]) -> dict[str, Any]:
    """A source's fields the caller set; an unset connection leaves the module's in place."""
    return {k: v for k, v in source.items() if v is not None}


def _refuse_during_review(m: Aggregate, what: str) -> None:
    """While a version waits for Security, what it approves must be exactly what calls switch to: an edit, a discard
    or another version on top would ride along unreviewed or leave the approval deciding nothing."""
    if any(v["status"] == "in_review" for v in m["versions"]):
        raise Conflict(f"A version is waiting for Security's review; {what} once it is decided.")


class ModuleService:
    def __init__(
        self,
        store: ModuleStore,
        directory: Directory,
        calls: CallLog,
        *,
        egress: EgressPolicy | None = None,
        http: httpx.AsyncClient | None = None,
        secrets: SecretResolver | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        security_team: str = "team_security",
        workflows: WorkflowDirectory | None = None,
        reviews: ReviewOpener | None = None,
        publish_policy: PublishPolicy | None = None,
        requester_policy: RequesterMayDecide | None = None,
        auth: Authenticator | None = None,
    ) -> None:
        """`egress` and `http` are what discovery and the test console's real reads go through: the same policy and
        client as the http executor. Without a policy, neither is available. `secrets` resolves a `{{NAME}}` header for
        a real read, as /v1/calls does."""
        self.store = store
        self.dir = directory
        # agents-service's workflows; without a directory none is known, so every approval request is refused.
        self.workflows: WorkflowDirectory = workflows or StaticWorkflows()
        self.calls = calls
        self.egress = egress
        self.http = http or (egress_client(egress) if egress else None)
        self.secrets = secrets
        self.clock = clock
        self.security_team = security_team
        # agents-service's Reviews, where a version's review opens (c-163); without it no review can open.
        self.reviews = reviews
        # The team's publish-review mode, read live from platform-service on each publish (c-139, c-214). Without a
        # reader (no platform URL, the tests) a publish follows the default "major": a major version waits.
        self.publish_policy = publish_policy
        # requesterMayDecide for access decisions applied for a workflow; without it the asker never decides.
        self.requester_policy = requester_policy
        # The tenant's connections (c-330), in this service's own database.
        self.connections = ConnectionStore(store.engine)
        # The operations' mock answers (c-332), which Try it's test answer reads as a test run does.
        self.mocks = MockAnswers(MockStore(store.engine))
        # Signs the test console's real reads in through the module's connection, in the test environment; without it
        # a connection adds nothing to them.
        self.auth = auth

    # ── Derived views ─────────────────────────────────────────────────────

    def _approval_status(self, a: dict[str, Any]) -> str:
        expired = a["status"] == "approved" and a["expires_at"] is not None and a["expires_at"] < self.clock()
        return "expired" if expired else a["status"]

    def _approvals(self, m: Aggregate) -> list[dict[str, Any]]:
        return [{**a, "status": self._approval_status(a)} for a in m["approvals"]]

    def _owners(self, m: Aggregate) -> list[str | None]:
        """The module's owner group and those of the teams owning the workflows it is approved for, as each approval
        recorded them when it was requested (the workflow's team comes from agents-service, c-039)."""
        return self.dir.owners(m)

    def _workflow_groups(self, a: dict[str, Any]) -> list[str | None]:
        team = self.dir.team_by_id(a.get("workflow_team_id"))
        return list(team.owner_groups) if team else []

    def _since(self, delta: timedelta) -> str:
        """`delta` before now, in the call log's created_at format, so the two compare as text."""
        return (self.clock() - delta).astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    async def _traffic(self, tenant_id: str, mods: list[Aggregate]) -> Traffic:
        since = self._since(timedelta(days=1))
        return await self.calls.traffic([m["id"] for m in mods], since, tenant_id=tenant_id)

    async def _secret_names(self, tenant_id: str, mods: list[Aggregate]) -> dict[str | None, set[str]]:
        """The names of the secrets each of the modules' teams has set (c-509: a module reads its own team's only);
        values are never read here."""
        if self.secrets is None:
            return {}
        owners = sorted({str(m["team_id"]) for m in mods if m["team_id"]})
        return {team: {str(r["name"]) for r in await self.secrets.store.listed(tenant_id, team)} for team in owners}

    async def _connections_of(self, tenant_id: str, mods: list[Aggregate]) -> dict[str, dict[str, Any]]:
        return await self.connections.by_ids(
            tenant_id, sorted({str(m["connection_id"]) for m in mods if m["connection_id"]})
        )

    def _row(
        self,
        m: Aggregate,
        traffic: Traffic,
        have: dict[str | None, set[str]] | None = None,
        conns: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        now = self.clock()
        conn = (conns or {}).get(m["connection_id"] or "")
        ops = m["operations"]
        t = traffic.get((m["id"], None), NO_TRAFFIC)
        approvals = self._approvals(m)
        active = [a for a in approvals if a["status"] == "approved"]
        expired = [a for a in approvals if a["status"] == "expired"]
        pending = sum(1 for a in approvals if a["status"] == "requested")
        expiries = sorted(a["expires_at"] for a in active if a["expires_at"] is not None)
        next_expiry = expiries[0] if expiries else None
        review_open = _review_open(m)
        if m["status"] == "draft":
            state = "draft"
        elif m["status"] != "published" or review_open or m["drift"] or pending:
            state = "needs_approval"
        elif not active and expired:
            state = "expired"
        elif next_expiry is not None and next_expiry - now < EXPIRING:
            state = "expiring"
        else:
            state = "approved"
        workflows = {a["workflow_id"]: {"id": a["workflow_id"], "name": a["workflow_name"]} for a in active}
        status = status_of(conn, now) if conn else ""
        row: dict[str, Any] = {
            "id": m["id"],
            "name": m["name"],
            "displayName": m["display_name"],
            "system": m["system"],
            "description": m["description"],
            "type": m["type"],
            "status": m["status"],
            "version": m["version"],
            "major": major_of(m["version"]),
            "ownerTeam": m["owner_team"],
            "endpoint": m["endpoint"],
            "operationCount": len(ops),
            "accessClasses": [acc for acc in ACCESS_ORDER if any(o["access"] == acc for o in ops)],
            "approvalState": state,
            "pendingApprovals": pending,
            "workflows": list(workflows.values()),
            **_rates(t),
            # A connection that is revoked, expired or failing makes the system unreachable from the gateway.
            "reachable": m["reachable"] and status not in ("revoked", "needs_reconnect", "error"),
            "drift": m["drift"],
            "connection": ref_of(conn, now) if conn else None,
            "updatedAt": _iso(m["updated_at"]),
        }
        if next_expiry is not None:
            row["nextExpiry"] = _iso(next_expiry)
        waiting = next((v for v in m["versions"] if v["status"] == "in_review" and v.get("review_id")), None)
        row["pendingReview"] = (
            {
                "id": waiting["review_id"],
                "version": waiting["version"],
                "requestedBy": waiting["published_by"],
                "requestedAt": _iso(waiting["requested_at"]),
            }
            if waiting
            else None
        )
        if m["connection_id"]:
            row["connectionId"] = m["connection_id"]
        row["templateId"], row["protection"] = m.get("template_id"), m.get("protection")
        if have is not None:
            needed = {n for o in ops for n in secret_names(o)}
            row["unsetSecrets"] = len(needed - have.get(m["team_id"], set()))
        return row

    def _in_view(self, r: dict[str, Any], view: str) -> bool:
        now = self.clock()
        if view == "all":
            return True
        if view == "needs_approval":
            return r["approvalState"] in ("needs_approval", "draft")
        if view == "expired":
            return r["approvalState"] == "expired"
        if view == "security_review":
            return r.get("pendingReview") is not None
        if view == "expiring":
            nxt = r.get("nextExpiry")
            return r["approvalState"] != "expired" and nxt is not None and datetime.fromisoformat(nxt) - now < EXPIRING
        return r["errorRate"] >= FAILING_RATE or not r["reachable"]

    def _run_contexts(self, m: Aggregate, team: Team) -> list[dict[str, Any]]:
        """The module owner first, which needs no workflow approval (c-048 T008), so the run panel's default is a try
        the owner can always make; then one context per workflow this module is approved for or asked for, with no
        case: the builder types the bound values, which the panel marks as a sample (c-039). Only the caller's team's
        workflows: running as another team's workflow would borrow its approval."""
        seen: dict[str, dict[str, Any]] = {}
        for a in m["approvals"]:
            ours = a.get("workflow_team_id") == team.id or self.dir.sees(team, self._workflow_groups(a))
            if a["workflow_id"] not in seen and ours:
                seen[a["workflow_id"]] = a
        owner: dict[str, Any] = {
            "id": OWNER_CONTEXT,
            "label": "Module owner, no case",
            "workflowId": "",
            "workflowName": "",
            "caseId": SAMPLE_CASE,
            "bindings": {},
        }
        return [owner] + [
            {
                "id": w,
                "label": f"{a['workflow_name']} · sample values",
                "workflowId": w,
                "workflowName": a["workflow_name"],
                "caseId": SAMPLE_CASE,
                "bindings": {},
            }
            for w, a in seen.items()
        ]

    def _operation(
        self,
        m: Aggregate,
        o: dict[str, Any],
        approvals: list[dict[str, Any]],
        t: dict[str, Any],
        have: dict[str | None, set[str]] | None = None,
    ) -> dict[str, Any]:
        policy = approval_policy(m, o)
        out: dict[str, Any] = {
            "id": o["id"],
            "toolId": o["tool_id"],
            "name": o["name"],
            "description": o["description"],
            "access": o["access"],
            "enabled": o["enabled"],
            "input": o["input"],
            "maskedOutput": o["masked_output"],
            "binding": o["binding"],
            "rateLimitPerMin": o["rate_limit_per_min"],
            "requiresApproval": o["requires_approval"],
            "approvers": policy["approvers"],
            "approverTeam": policy["approver_team"],
            "stepUp": policy["step_up"],
            "idempotent": o["access"] != "read",
            **_rates(t),
            "approvedWorkflows": len(
                {a["workflow_id"] for a in approvals if a["status"] == "approved" and o["name"] in a["operations"]}
            ),
        }
        for key, col in (("method", "method"), ("path", "path")):
            if o[col] is not None:
                out[key] = o[col]
        out["executor"] = o["executor"]
        if o.get("code"):
            out["code"] = o["code"]
        out["headers"] = o.get("headers") or []
        for key, col in (("body", "body"), ("responseTransform", "response_transform"), ("timeoutMs", "timeout_ms")):
            if o.get(col) is not None:
                out[key] = o[col]
        if o["amount_max"] is not None:
            out["amountMax"] = float(o["amount_max"])
        if have is not None:
            # Set in the module's own team, the only secrets the gateway reads for it; `available` says the same, for
            # callers written when a secret could be limited to some teams.
            mine = have.get(m["team_id"], set())
            out["secrets"] = [{"name": n, "set": n in mine, "available": n in mine} for n in secret_names(o)]
        out["stub"] = o.get("stub")
        return out

    def _rights(self, who: Caller, m: Aggregate) -> dict[str, bool]:
        """What the caller may do with this module (c-186), by the check each write route runs: `can` for the action
        with the module's protection, so the console's buttons and the routes never disagree."""
        out: dict[str, bool] = {}
        for action in ("edit", "delete", "publish"):
            try:
                _can(who, "tools", action, what="it", security_team=self.security_team, protection=m.get("protection"))
            except Forbidden:
                out[f"can{action.capitalize()}"] = False
            else:
                out[f"can{action.capitalize()}"] = True
        return out

    async def _detail(self, m: Aggregate, team: Team, who: Caller | None = None) -> dict[str, Any]:
        """`who` is the person asking; their rights on the module ride along. A service applying a decision has none."""
        traffic = await self._traffic(str(m["tenant_id"]), [m])
        have = await self._secret_names(str(m["tenant_id"]), [m])
        approvals = self._approvals(m)
        ordered = sorted(
            approvals,
            key=lambda a: (STATUS_ORDER[a["status"]], _iso(a["expires_at"]) or "9"),
        )
        auth = {k: v for k, v in m["auth"].items() if v is not None}
        return {
            **self._row(m, traffic, have, await self._connections_of(str(m["tenant_id"]), [m])),
            "ownerContacts": m["owner_contacts"],
            "auth": auth,
            "timeoutMs": m["timeout_ms"],
            "egressHosts": m["egress_hosts"],
            "dataClassification": m["data_classification"],
            "operations": [
                self._operation(m, o, approvals, traffic.get((m["id"], o["name"]), NO_TRAFFIC), have)
                for o in m["operations"]
            ],
            "pendingChanges": m["pending"],
            "approvals": [self._approval_out(a) for a in ordered],
            "versions": [self._version_out(v) for v in reversed(m["versions"])],
            "runContexts": self._run_contexts(m, team),
            **(self._rights(who, m) if who is not None else {}),
        }

    @staticmethod
    def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in d.items() if v is not None}

    def _approval_out(self, a: dict[str, Any]) -> dict[str, Any]:
        return self._drop_none(
            {
                "id": a["id"],
                "workflowId": a["workflow_id"],
                "workflowName": a["workflow_name"],
                "environment": a["environment"],
                "major": a["major"],
                "operations": a["operations"],
                "constraints": a["constraints"],
                "requestedBy": a["requested_by"],
                "justification": a["justification"],
                "requestedAt": _iso(a["requested_at"]),
                "decidedBy": a["decided_by"],
                "decidedAt": _iso(a["decided_at"]),
                "status": a["status"],
                "expiresAt": _iso(a["expires_at"]),
                "reason": a["reason"],
                # The Human Tasks review deciding it and the team whose reviewers do (c-166).
                "reviewId": a.get("review_id"),
                "deciderTeam": a.get("decider_team"),
            }
        )

    def _version_out(self, v: dict[str, Any]) -> dict[str, Any]:
        return self._drop_none(
            {
                "version": v["version"],
                "major": v["major"],
                "status": v["status"],
                "publishedAt": _iso(v["published_at"]),
                "publishedBy": v["published_by"],
                "note": v["note"],
                "changes": v["changes"],
                "pinnedBy": v["pinned_by"],
                "reachability": v["reachability"],
                "reviewId": v.get("review_id"),
                "requestedAt": _iso(v.get("requested_at")),
                "reviewer": v.get("reviewer"),
                "finding": v.get("finding"),
                "reviewRequired": v.get("review_required"),
                "policy": v.get("policy"),
            }
        )

    # ── Loading and saving ────────────────────────────────────────────────

    async def _find(self, who: Caller, module_id: str) -> Aggregate:
        m = await self.store.get(who.tenant_id, module_id)
        if m is None or not self._sees(who, m):
            raise NotFound("Module")
        return m

    def _sees(self, who: Caller, m: Aggregate) -> bool:
        """The caller's team reads the module: its own, a workspace-level one, or one approved for its workflows
        (c-423). Only the dev header caller acting in one of the dev seed's all-scope teams reads every team's."""
        return self.dir.sees_module(who.team, m) or (not who.verified and who.team.scope == "all")

    async def _changeable(self, who: Caller, module_id: str, action: str = "edit") -> Aggregate:
        """The module, when the caller may change it: a `system` module is the provisioner's alone (c-180)."""
        m = await self._find(who, module_id)
        _can(
            who,
            "tools",
            action,
            what=f"{m['display_name']}",
            security_team=self.security_team,
            protection=m.get("protection"),
        )
        return m

    async def _save(self, m: Aggregate, *, touch: bool = True, events: Sequence[dict[str, Any]] = ()) -> Aggregate:
        """`events` are service events written in the same transaction (c-258)."""
        if touch:
            m["updated_at"] = self.clock()
        try:
            return await self.store.put(m, expected_revision=m["revision"], events=events)
        except StaleModuleError as e:
            raise Conflict("Someone else changed this module while you were editing. Reload and try again.") from e
        except HostNotAllowedError as e:
            raise _not_allowed(e.host) from e

    async def _create(self, m: Aggregate) -> Aggregate:
        try:
            return await self.store.put(m, expected_revision=None)
        except HostNotAllowedError as e:
            raise _not_allowed(e.host) from e

    # ── Reads ─────────────────────────────────────────────────────────────

    def _grant_views(self, a: dict[str, Any], now: datetime) -> set[str]:
        """The Access tab's views an approval is in: approved is active (and expiring within a week), requested waits,
        an approval past its end is expired, and a rejected or revoked one has ended."""
        status, views = a["status"], {"all"}
        if status == "approved":
            views.add("active")
            if a["expires_at"] is not None and a["expires_at"] - now < EXPIRING:
                views.add("expiring")
        elif status == "requested":
            views.add("requested")
        elif status == "expired":
            views.add("expired")
        elif status in ("rejected", "revoked"):
            views.add("ended")
        return views

    async def grants(self, who: Caller, *, view: str, search: str | None, page: int, page_size: int) -> dict[str, Any]:
        """Every workflow's access to the modules the caller's team sees, newest request first, one page of `view`,
        searched by workflow, module or requester; `facets.view` counts each view."""
        now = self.clock()
        mods = [m for m in await self.store.all(who.tenant_id) if self._sees(who, m)]
        rows = [(a, m) for m in mods for a in self._approvals(m)]
        views = {id(a): self._grant_views(a, now) for a, _ in rows}
        counts = {v: sum(1 for a, _ in rows if v in views[id(a)]) for v in GRANT_VIEWS}
        q = (search or "").lower()

        def matches(a: dict[str, Any], m: Aggregate) -> bool:
            said = f"{a['workflow_name']} {a['workflow_id']} {m['display_name']} {m['name']} {a['requested_by']}"
            return not q or q in said.lower()

        picked = [(a, m) for a, m in rows if view in views[id(a)] and matches(a, m)]
        picked.sort(key=lambda x: (x[0]["requested_at"], x[0]["id"]), reverse=True)
        out = [{**self._approval_out(a), "moduleId": m["id"], "moduleName": m["display_name"]} for a, m in picked]
        listed = paged(out[(page - 1) * page_size : page * page_size], len(out), page, page_size)
        return listed | {"facets": {"view": counts}}

    async def list(
        self,
        who: Caller,
        *,
        page: int,
        page_size: int,
        view: str,
        search: str | None,
        filters: dict[str, list[str]],
        sort_by: str | None,
        sort_order: str | None,
    ) -> dict[str, Any]:
        now = self.clock()
        mods = [m for m in await self.store.all(who.tenant_id) if self._sees(who, m)]
        traffic = await self._traffic(who.tenant_id, mods)
        have = await self._secret_names(who.tenant_id, mods)
        conns = await self._connections_of(who.tenant_id, mods)
        rows = [self._row(m, traffic, have, conns) for m in mods]
        counts = {"all": len(rows)} | {
            v: sum(1 for r in rows if self._in_view(r, v))
            for v in ("needs_approval", "expiring", "expired", "failing", "security_review")
        }

        def values(r: dict[str, Any], key: str) -> list[str]:
            return list(r["accessClasses"]) if key == "access" else [str(r.get(key))]

        q = (search or "").lower()
        searched = [
            r
            for r in rows
            if self._in_view(r, view)
            and (
                not q
                or q in f"{r['displayName']} {r['name']} {r['system']} {r['description']} {r['ownerTeam']}".lower()
            )
        ]
        active = {k: v for k, v in filters.items() if v}

        def match(r: dict[str, Any], skip: str | None = None) -> bool:
            return all(k == skip or any(x in v for x in values(r, k)) for k, v in active.items())

        filtered = [r for r in searched if match(r)]
        # Each facet counts rows under every other active filter, so its options show what selecting them would yield.
        facets: dict[str, dict[str, int]] = {}
        for key in ("type", "access", "approvalState"):
            facet: dict[str, int] = {}
            for r in (x for x in searched if match(x, key)):
                for val in values(r, key):
                    facet[val] = facet.get(val, 0) + 1
            facets[key] = facet
        if sort_by in ("displayName", "name", "calls24h", "errorRate", "updatedAt", "operationCount", "ownerTeam"):
            filtered.sort(key=lambda r: r[sort_by], reverse=sort_order == "desc")
        total = len(filtered)
        total_pages = max(1, -(-total // page_size))
        page = min(page, total_pages)
        calls = sum(r["calls24h"] for r in rows)
        errors = sum(r["calls24h"] * r["errorRate"] for r in rows)
        expiring_approvals = sum(
            1
            for m in mods
            for a in self._approvals(m)
            if a["status"] == "approved" and a["expires_at"] is not None and a["expires_at"] - now < EXPIRING
        )
        return {
            "data": filtered[(page - 1) * page_size : page * page_size],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": total_pages,
                "hasNext": page < total_pages,
                "hasPrev": page > 1,
            },
            "facets": facets,
            "stats": {
                "modules": len(rows),
                "operations": sum(r["operationCount"] for r in rows),
                "calls24h": calls,
                "errorRate": errors / calls if calls else 0,
                "expiringApprovals": expiring_approvals,
                "expiringModules": counts["expiring"],
            },
            "viewCounts": counts,
        }

    async def get(self, who: Caller, module_id: str) -> dict[str, Any]:
        return await self._detail(await self._find(who, module_id), who.team, who)

    async def activity(self, who: Caller, module_id: str) -> dict[str, Any]:
        """Calls per UTC day over the last 14 days from the call log, days without calls at zero."""
        m = await self._find(who, module_id)
        today = self.clock().astimezone(UTC).date()
        first = today - timedelta(days=13)
        logged = await self.calls.daily(m["id"], first.isoformat(), tenant_id=who.tenant_id)
        days = [
            {"date": d, **logged.get(d, {"count": 0, "errors": 0, "p95Ms": 0})}
            for d in ((first + timedelta(days=i)).isoformat() for i in range(14))
        ]
        since = self._since(timedelta(days=1))
        tenant = who.tenant_id
        _, denied = await self.calls.search(
            tenant_id=tenant, module_ids=[m["id"]], decision="deny", since=since, limit=1
        )
        recent, _ = await self.calls.search(tenant_id=tenant, module_ids=[m["id"]], limit=12)
        return {"days": days, "denied24h": denied, "recent": [call_row(r, _workflow_names([m]), m) for r in recent]}

    async def executions(
        self,
        who: Caller,
        *,
        page: int,
        page_size: int,
        tool: str | None,
        module_id: str | None,
        thread_id: str | None,
        decision: str | None,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Every call the gateway received, newest first, limited to the modules the caller's team sees. `key` finds
        the calls sent under one idempotency key: how a workflow run reconciles a write after a crash."""
        mods = {m["id"]: m for m in await self.store.all(who.tenant_id) if self._sees(who, m)}
        scope = None if not who.verified and who.team.scope == "all" else list(mods)
        if module_id is not None:
            scope = [module_id] if scope is None or module_id in scope else []
        if key is not None:
            # A lookup by key shows a claim as it stands: one still running past its expiry reads as lost.
            await self.calls.expire_running(tenant_id=who.tenant_id, key=key)
        rows, total = await self.calls.search(
            tenant_id=who.tenant_id,
            tools=[tool] if tool else None,
            module_ids=scope,
            thread_id=thread_id,
            decision=decision,
            key=key,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        pages = max(1, -(-total // page_size))
        names = _workflow_names(list(mods.values()))
        return {
            "data": [call_row(r, names, mods.get(r["module_id"] or "")) for r in rows],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": pages,
                "hasNext": page < pages,
                "hasPrev": page > 1,
            },
            "facets": {},
        }

    async def execution(self, who: Caller, call_id: str) -> dict[str, Any]:
        """One call from the gateway's log, so an Activity row opens to its call. The same scope as the list: a call
        on a module the caller's team does not see is not found, never a different answer."""
        row = await self.calls.get(call_id, tenant_id=who.tenant_id)
        if row is None:
            raise NotFound("Call")
        mods = {m["id"]: m for m in await self.store.all(who.tenant_id) if self._sees(who, m)}
        if (who.verified or who.team.scope != "all") and row["module_id"] not in mods:
            raise NotFound("Call")
        return call_row(row, _workflow_names(list(mods.values())), mods.get(row["module_id"] or ""))

    # ── Creating modules ──────────────────────────────────────────────────

    @staticmethod
    def _checked_headers(headers: list[dict[str, str]]) -> list[dict[str, str]]:
        """A literal credential in a header is refused: credentials live on the connection or in the vault,
        referenced as {{NAME}}. Used by add and edit alike."""
        for header in headers:
            key, value = header["key"].strip(), header["value"].strip()
            if CREDENTIAL_HEADER.match(key) and value and not SECRET_REFERENCE.match(value):
                raise ValidationFailed(
                    f"The {header['key']} header holds a literal value. Reference the vault instead, e.g. "
                    "{{CORE_API_KEY}}."
                )
        return [{"key": h["key"].strip(), "value": h["value"].strip()} for h in headers if h["key"].strip()]

    @staticmethod
    def _split_url(url: str, endpoint: str) -> tuple[str, str]:
        """The base an operation's URL hangs off and its path. https only. A module with an endpoint calls every
        operation on it (the executor joins the endpoint and the path), so a URL on any other base is refused: a
        second system is a second module."""
        parts = urlsplit(URL_VAR.sub("x", url))
        if parts.scheme != "https" or not parts.netloc:
            raise ValidationFailed("Enter the full https URL of the operation.")
        base = endpoint.rstrip("/") or f"https://{parts.netloc}"
        if url != base and not url.startswith(f"{base}/"):
            raise ValidationFailed(
                f"https://{parts.netloc} is not this module's endpoint ({base}). A second system is a second module."
            )
        return base, url[len(base) :] or "/"

    @staticmethod
    def _body_problem(body: str | None) -> str | None:
        """Why a body template would not make JSON once its {{arg}} placeholders are filled, or None."""
        if not body or not body.strip():
            return None
        try:
            json.loads(BODY_VAR.sub("null", body))
        except json.JSONDecodeError as e:
            return f"The body is not a JSON template: {e.msg} at line {e.lineno}."
        return None

    def _http_operation(self, h: dict[str, Any], endpoint: str = "") -> tuple[dict[str, Any], str]:
        """One hand-built HTTP operation as a discovered one, and the base it calls."""
        headers = self._checked_headers(h.get("headers") or [])
        if not OPERATION_NAME.match(h["name"]):
            raise ValidationFailed("Name the operation in lower case letters, digits and underscores.")
        origin, path = self._split_url(h["url"], endpoint)
        if problem := self._body_problem(h.get("body")):
            raise ValidationFailed(problem)
        names = [*URL_VAR.findall(h["url"]), *BODY_VAR.findall(h.get("body") or "")]
        op = {
            "name": h["name"],
            "description": h["description"],
            "access": h["access"],
            "method": h["method"],
            "path": path,
            "group": "operations",
            "input": [_sample_field(n) for n in dict.fromkeys(names)],
            "headers": headers,
            "body": h.get("body"),
        }
        return op, origin

    @staticmethod
    def _added(o: dict[str, Any], *, major: bool) -> dict[str, Any]:
        return {"operation": o["name"], "kind": "added", "detail": f"New {o['access']} operation", "major": major}

    def _new_op(self, module_id: str, index: int, o: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"{module_id}_op{index}",
            "tool_id": new_id("tl"),
            "name": o["name"],
            "description": o["description"],
            "access": o["access"],
            "enabled": True,
            "executor": o.get("executor", "http"),
            "method": o.get("method"),
            "path": o.get("path"),
            "headers": o.get("headers") or [],
            "body": o.get("body"),
            "response_transform": None,
            "timeout_ms": None,
            "input": o["input"],
            "masked_output": [],
            "binding": None,
            "rate_limit_per_min": 60,
            "requires_approval": o["access"] != "read",
            "amount_max": None,
            # The source's example response when it gives one, so a stubbed call answers like the system.
            "stub": o.get("stub") if o.get("stub") is not None else {"ok": True},
            "output_shape": o.get("output_shape"),
            "response_schema": o.get("response_schema"),
            "code": o.get("code"),
        }

    async def _names_free(self, who: Caller, ops: list[dict[str, Any]]) -> None:
        taken = await self.store.names_taken(who.tenant_id, [o["name"] for o in ops], who.team.id)
        if taken:
            name = sorted(taken)[0]
            raise Conflict(f"An operation named {name} already exists in another module.")

    async def _name_free(self, who: Caller, name: str) -> bool:
        return name not in await self.store.names(who.tenant_id, who.team.id)

    async def create(self, who: Caller, i: dict[str, Any]) -> dict[str, Any]:
        _can(who, "tools", "create", what="tool modules", security_team=self.security_team)
        template = _provisioned(who, i)
        base = _kebab(i["name"])
        if not base:
            raise ValidationFailed("Name the module.")
        name = base
        if i.get("unique_name"):
            n = 2
            while not await self._name_free(who, name):
                name, n = f"{base}-{n}", n + 1
        if not await self._name_free(who, name):
            raise Conflict(f"A module named {name} already exists.")
        if not i["display_name"].strip():
            raise ValidationFailed("Give the module a display name.")
        # A module's endpoint and its secret headers are its connection (docs/architecture/tool-lifecycle.md); a
        # connection record is optional, and when one is named it must exist and be live.
        conn = None
        if i.get("connection_id") is not None:
            conn = await self.connections.get(who.tenant_id, i["connection_id"])
            if conn is None:
                raise ValidationFailed("That connection no longer exists. Pick another one, or none.")
            if status_of(conn, self.clock()) == "revoked":
                raise Conflict(f"{conn['name']} is revoked. Reconnect it in Connections or pick another connection.")
            if not may_use(conn, who.team.id):
                raise ValidationFailed(f"{conn['name']} is not available to this team. Pick another one, or none.")
        ops_in: list[dict[str, Any]] = list(i.get("operations") or [])
        if i["type"] == "code":
            # A code module's functions run on runner-service (c-531): no endpoint and no egress host of its own.
            if not i.get("function"):
                raise ValidationFailed("Write the module's first function.")
            ops_in = [_code_operation(i["function"])]
        endpoint: str = i["endpoint"]
        if i.get("source") and ops_in:
            # An MCP server behind sign-in lists its tools only with the connection's token (c-331).
            found = await self._discover(who, {"connection_id": i.get("connection_id"), **_given(i["source"])})
            ops_in = self._chosen(found, ops_in)
            endpoint = found["endpoint"]
        if i.get("http"):
            op, endpoint = self._http_operation(i["http"])
            ops_in = [op]
        if not ops_in:
            raise ValidationFailed("Choose at least one operation to expose.")
        await self._names_free(who, ops_in)
        module_id = new_id("mod")
        now = self.clock()
        # The creator's team approves the module's writes; an all-scope team (team_ops) has no owner group to map from.
        owner = self.dir.owner_group(who.team) or "Platform"
        host = urlsplit(endpoint).hostname
        version = "1.0.0"
        m: Aggregate = {
            **blank(
                module_id=module_id,
                tenant_id=who.tenant_id,
                team_id=who.team.id,
                owner=owner,
                me=who.name,
                at=now,
                input={"displayName": i["display_name"], "name": name, "type": i["type"]},
            ),
            "system": i["system"].strip() or i["display_name"].strip(),
            "description": f"{i['system']} operations behind the data gateway.",
            "endpoint": endpoint,
            "auth": module_auth(conn),
            "egress_hosts": [host] if host else [],
            "catalog_id": conn.get("catalog_id") if conn else None,
            "connection_id": conn["id"] if conn else None,
            "version": version,
            "operations": [self._new_op(module_id, n + 1, o) for n, o in enumerate(ops_in)],
        }
        m["versions"] = [
            {
                **m["versions"][0],
                "id": f"{module_id}_v{version}",
                "version": version,
                "major": major_of(version),
                "changes": [self._added(o, major=True) for o in ops_in],
                "reachability": [{"environment": "test", "ok": True, "checkedAt": now.isoformat()}],
            }
        ]
        m.update(template)
        return await self._detail(await self._create(m), who.team, who)

    async def create_blank(self, who: Caller, i: dict[str, Any]) -> dict[str, Any]:
        _can(who, "tools", "create", what="tool modules", security_team=self.security_team)
        template = _provisioned(who, i)
        name = _kebab(i["name"])
        if not i["display_name"].strip():
            raise ValidationFailed("Give the module a display name.")
        if not name:
            raise ValidationFailed("Give the module a name, e.g. servicenow.")
        if not await self._name_free(who, name):
            raise Conflict(f"A module named {name} already exists.")
        owner = self.dir.owner_group(who.team) or "Platform"
        m = blank(
            module_id=new_id("mod"),
            tenant_id=who.tenant_id,
            team_id=who.team.id,
            owner=owner,
            me=who.name,
            at=self.clock(),
            input={**i, "displayName": i["display_name"], "name": name},
        )
        m.update(template)
        return await self._detail(await self._create(m), who.team, who)

    # ── Editing ───────────────────────────────────────────────────────────

    async def update_details(self, who: Caller, module_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        _can(who, "tools", "edit", what="tool modules", security_team=self.security_team)
        m = await self._changeable(who, module_id)
        if patch.get("display_name") is not None:
            if not patch["display_name"].strip():
                raise ValidationFailed("Give the module a display name.")
            m["display_name"] = patch["display_name"].strip()
        if patch.get("description") is not None:
            m["description"] = patch["description"].strip()
        m.update(_provisioned(who, patch))
        return await self._detail(await self._save(m), who.team, who)

    def _stage(self, m: Aggregate, changes: list[dict[str, Any]]) -> None:
        pending: list[dict[str, Any]] = list(m["pending"])
        for c in changes:
            i = next(
                (n for n, p in enumerate(pending) if p["operation"] == c["operation"] and p["kind"] == c["kind"]), -1
            )
            if i >= 0:
                pending[i] = c
            else:
                pending.append(c)
        m["pending"] = pending

    @staticmethod
    def _take_baseline(m: Aggregate) -> None:
        """Keeps the published operations as the baseline calls run while edits wait for review. A module never
        published runs no call, so its edits apply as made and the first review approves them."""
        ever_published = m["status"] == "published" or any(
            v["status"] in ("published", "deprecated") for v in m["versions"]
        )
        if m["baseline"] is None and ever_published:
            m["baseline"] = json.loads(json.dumps(m["operations"], default=str))

    async def _append(self, who: Caller, m: Aggregate, ops_in: list[dict[str, Any]]) -> None:
        """Appends operations. A draft takes them straight into its first version; a published module stages them."""
        _refuse_during_review(m, "add operations")
        for o in ops_in:
            if any(x["name"] == o["name"] for x in m["operations"]):
                raise Conflict(f"{o['name']} is already in this module.")
        await self._names_free(who, ops_in)
        self._take_baseline(m)
        start = len(m["operations"])
        m["operations"] = [*m["operations"], *(self._new_op(m["id"], start + n + 1, o) for n, o in enumerate(ops_in))]
        # Any new operation widens what the module can do, so publish sends it to Security (_differs_from_published);
        # the staged change says so, read or write, and the module page offers the major publish it will be.
        changes = [self._added(o, major=True) for o in ops_in]
        if m["status"] == "draft":
            last = m["versions"][-1]
            m["versions"] = [*m["versions"][:-1], {**last, "changes": [*last["changes"], *changes]}]
        else:
            self._stage(m, changes)

    async def add_operation(self, who: Caller, module_id: str, h: dict[str, Any]) -> dict[str, Any]:
        _can(who, "tools", "edit", what="tool modules", security_team=self.security_team)
        m = await self._changeable(who, module_id)
        op, origin = self._http_operation(h, m["endpoint"] or "")
        if not m["endpoint"]:
            m["endpoint"] = origin
        host = urlsplit(origin).hostname
        if host and host not in m["egress_hosts"]:
            m["egress_hosts"] = [*m["egress_hosts"], host]
        await self._append(who, m, [op])
        return await self._detail(await self._save(m), who.team, who)

    async def set_connection(self, who: Caller, module_id: str, connection_id: str | None) -> dict[str, Any]:
        _can(who, "tools", "edit", what="tool modules", security_team=self.security_team)
        m = await self._changeable(who, module_id)
        if connection_id is None:
            if m["status"] != "draft":
                raise Conflict(
                    "A module in review or published keeps its connection. Change it to another one instead."
                )
            m.update(connection_id=None, catalog_id=None, auth={"kind": "none"})
        else:
            conn = await self.connections.get(who.tenant_id, connection_id)
            if conn is None:
                raise ValidationFailed("That connection no longer exists. Pick another one.")
            if status_of(conn, self.clock()) == "revoked":
                raise Conflict(f"{conn['name']} is revoked. Reconnect it in Connections or pick another one.")
            if not may_use(conn, m["team_id"]):
                raise ValidationFailed(f"{conn['name']} is not available to this module's team. Pick another one.")
            m.update(connection_id=conn["id"], catalog_id=conn.get("catalog_id"), auth=module_auth(conn))
        return await self._detail(await self._save(m), who.team, who)

    def _holders(self, m: Aggregate) -> list[str]:
        return list(dict.fromkeys(a["workflow_name"] for a in self._approvals(m) if a["status"] == "approved"))

    async def remove(self, who: Caller, module_id: str) -> None:
        _can(who, "tools", "delete", what="tool modules", security_team=self.security_team)
        m = await self._changeable(who, module_id, "delete")
        holders = self._holders(m)
        if holders:
            verb, them = ("holds an approval", "it") if len(holders) == 1 else ("hold approvals", "them")
            raise Conflict(f"{', '.join(holders)} {verb} for this module. Revoke {them} first.")
        await self.store.delete(who.tenant_id, module_id)

    async def bulk_remove(self, who: Caller, ids: list[str]) -> dict[str, Any]:
        _can(who, "tools", "delete", what="tool modules", security_team=self.security_team)
        out: dict[str, Any] = {"updated": [], "skipped": []}
        for module_id in ids:
            m = await self.store.get(who.tenant_id, module_id)
            if m is None or not self._sees(who, m):
                out["skipped"].append({"id": module_id, "reason": "Not found"})
                continue
            try:
                # As a single delete: can() with the module's protection, so an admin removes a system module too.
                _can(
                    who,
                    "tools",
                    "delete",
                    what=str(m["display_name"]),
                    security_team=self.security_team,
                    protection=m.get("protection"),
                )
            except Forbidden as e:
                out["skipped"].append({"id": module_id, "reason": e.message})
                continue
            holders = self._holders(m)
            if holders:
                reason = f"Approved for {holders[0] if len(holders) == 1 else f'{len(holders)} workflows'}"
                out["skipped"].append({"id": module_id, "reason": reason})
                continue
            await self.store.delete(who.tenant_id, module_id)
            out["updated"].append(module_id)
        return out

    async def update_operation(
        self, who: Caller, module_id: str, op_id: str, patch: dict[str, Any], fields: set[str]
    ) -> dict[str, Any]:
        """`fields` names the keys the caller sent, so `binding: null` (remove it) differs from leaving it out."""
        _can(who, "tools", "edit", what="tool modules", security_team=self.security_team)
        m = await self._changeable(who, module_id)
        o = next((x for x in m["operations"] if x["id"] == op_id), None)
        if o is None:
            raise NotFound("Operation")
        _refuse_during_review(m, "edit operations")
        two = int(o.get("approvers") or 1) > 1 and patch.get("approvers") != 1
        if patch.get("requires_approval") is False and two:
            raise Unprocessable("An operation two people approve always needs a person's approval.")
        rate = patch.get("rate_limit_per_min")
        if rate is not None and not 1 <= rate <= 10_000:
            raise ValidationFailed("Set a rate limit between 1 and 10,000 calls a minute.")
        amount = patch.get("amount_max")
        if amount is not None and (o["access"] != "write" or amount <= 0):
            raise ValidationFailed("Only write operations take an amount limit, and it must be above zero.")
        if amount is not None and not any(f["name"] == "amount" for f in o["input"]):
            # The gateway reads the limit from the `amount` input; on an operation without one it could never hold.
            raise Unprocessable(f"{o['name']} has no amount input, so an amount limit would have nothing to check.")
        approvers = patch.get("approvers")
        if approvers is not None and approvers not in (1, 2):
            raise ValidationFailed("A write is approved by one person or by two different people.")
        team = patch.get("approver_team")
        # The directory is the console seed. A platform team the token names (the demo team) is not in that
        # list; the caller naming their own team is enough (c-509: a record belongs to the acting team).
        if team is not None and self.dir.team_by_id(team) is None and team != who.team.id:
            raise Unprocessable(f"{team} is not a team in this workspace.")
        binding = patch.get("binding")
        new_input = self._field_list(patch["input"]) if "input" in fields and patch.get("input") is not None else None
        names = {f["name"] for f in (new_input if new_input is not None else o["input"])}
        if binding and binding["arg"] not in names:
            raise ValidationFailed(f"{binding['arg']} is not an input of {o['name']}.")
        shape = self._checked_shape(m, o, patch, fields)
        # A path or body edit alone adds the placeholders it names as inputs (_shape_changes); a schema sent with it
        # must already list them.
        if new_input is not None:
            self._check_input(
                o,
                new_input,
                path=shape.get("path", o.get("path")),
                body=shape.get("body", o.get("body")) if "body" in shape else o.get("body"),
                binding=binding if "binding" in fields else o["binding"],
            )
        access = patch.get("access")
        self._take_baseline(m)
        changes: list[dict[str, Any]] = self._shape_changes(o, shape)
        name = o["name"]
        if new_input is not None:
            changes.extend(self._input_changes(o, new_input))
            o["input"] = new_input
        if access is not None and access != o["access"]:
            # Either way the agent-facing contract changes: a read that writes needs an approval, a write made a read
            # loses it. Security reviews both.
            detail = f"Access {o['access']} → {access}"
            changes.append({"operation": name, "kind": "access_widened", "detail": detail, "major": True})
            o["access"] = access
            o["requires_approval"] = access == "write"
            if access == "read":
                o["amount_max"] = None
        if patch.get("enabled") is not None and patch["enabled"] != o["enabled"]:
            # Hiding an operation a workflow is approved for breaks that workflow, so it is a major change.
            users = list(
                dict.fromkeys(
                    a["workflow_name"]
                    for a in self._approvals(m)
                    if a["status"] == "approved" and name in a["operations"]
                )
            )
            if patch["enabled"]:
                changes.append({"operation": name, "kind": "added", "detail": "Exposed to workflows", "major": True})
            elif users:
                verb = "calls" if len(users) == 1 else "call"
                detail = f"Hidden from workflows; breaks {', '.join(users)}, which {verb} it"
                changes.append({"operation": name, "kind": "removed", "detail": detail, "major": True})
            else:
                detail = "Hidden from workflows; no workflow is approved for it"
                changes.append({"operation": name, "kind": "removed", "detail": detail, "major": False})
            o["enabled"] = patch["enabled"]
        if patch.get("requires_approval") is not None and patch["requires_approval"] != o["requires_approval"]:
            on = patch["requires_approval"]
            detail = "Every call waits for an approval" if on else "Calls no longer wait for a person"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": not on})
            o["requires_approval"] = on
        if rate is not None and rate != o["rate_limit_per_min"]:
            detail = f"Rate limit {o['rate_limit_per_min']} → {rate} a minute"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": False})
            o["rate_limit_per_min"] = rate
        before = float(o["amount_max"]) if o["amount_max"] is not None else None
        if amount is not None and amount != before:
            detail = f"Amount limit ${before or 0:g} → ${amount:g}"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": amount > (before or 0)})
            o["amount_max"] = amount
        # Fewer approvers, another approving team or the asker approving their own call loosens the policy, so each
        # is a major change that Security reviews; tightening is minor.
        if approvers is not None and approvers != int(o.get("approvers") or 1):
            detail = f"Approvers {o.get('approvers') or 1} → {approvers}"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": approvers < 2})
            o["approvers"] = approvers
        if team is not None and team != o.get("approver_team"):
            detail = f"Approved by {team}"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": True})
            o["approver_team"] = team
        # Part of the approval policy, which Security reviews either way (publish compares it with the baseline).
        step_up = patch.get("step_up")
        if step_up is not None and step_up != bool(o.get("step_up")):
            detail = "Approving asks for a step-up" if step_up else "Approving no longer asks for a step-up"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": True})
            o["step_up"] = step_up
        if patch.get("description") is not None and patch["description"].strip() != o["description"]:
            changes.append({"operation": name, "kind": "settings", "detail": "Description edited", "major": False})
            o["description"] = patch["description"].strip()
        if "binding" in fields and binding != o["binding"]:
            old = o["binding"]
            widened = not binding or (
                old is not None
                and (
                    (old["required"] and not binding["required"])
                    or (old["mode"] == "equals" and binding["mode"] == "within")
                )
            )
            if binding:
                optional = "" if binding["required"] else ", optional"
                rel = "=" if binding["mode"] == "equals" else "within"
                detail = f"{binding['arg']} {rel} {binding['bindTo']}{optional}"
            else:
                detail = "No record binding"
            changes.append({"operation": name, "kind": "binding_changed", "detail": detail, "major": widened})
            o["binding"] = binding
        if "stub" in fields:
            stub = patch.get("stub")
            stub = {"ok": True} if stub is None else stub
            if len(json.dumps(stub)) > MAX_STUB_BYTES:
                raise ValidationFailed(f"Keep the mock response under {MAX_STUB_BYTES // 1000} KB.")
            if stub != o.get("stub"):
                # Minor, as a transform edit is: it changes what a stub executor and tests answer, not the contract.
                changes.append(
                    {"operation": name, "kind": "settings", "detail": "Mock response edited", "major": False}
                )
                o["stub"] = stub
        if "code" in fields and patch.get("code") is not None:
            changes.extend(self._code_changes(o, _code_settings(patch["code"])))
        if not changes:
            raise ValidationFailed("Nothing changed.")
        self._stage(m, changes)
        return await self._detail(await self._save(m), who.team, who)

    @staticmethod
    def _code_changes(o: dict[str, Any], code: dict[str, Any]) -> list[dict[str, Any]]:
        """Applies a code operation's new settings. A tool or secret it did not have widens what the function reaches,
        so Security reviews it; an edit to the source or the limits alone is minor."""
        if o["executor"] != "code":
            raise ValidationFailed(f"{o['name']} is not a code operation.")
        before = cast(dict[str, Any], o.get("code") or {})
        if code == before:
            return []
        added = [
            *(set(code["bindings"]) - set(before.get("bindings") or [])),
            *(set(code["secrets"]) - set(before.get("secrets") or [])),
        ]
        detail = f"May now use {', '.join(sorted(added))}" if added else "Function edited"
        o["code"] = code
        kind = "binding_changed" if added else "settings"
        return [{"operation": o["name"], "kind": kind, "detail": detail, "major": bool(added)}]

    async def add_function(self, who: Caller, module_id: str, f: dict[str, Any]) -> dict[str, Any]:
        """Adds a function to a code module (c-531)."""
        _can(who, "tools", "edit", what="tool modules", security_team=self.security_team)
        m = await self._changeable(who, module_id)
        if m["type"] != "code":
            raise ValidationFailed(f"{m['display_name']} is not a code module; add its operations from its system.")
        await self._append(who, m, [_code_operation(f)])
        return await self._detail(await self._save(m), who.team, who)

    def _checked_shape(
        self, m: Aggregate, o: dict[str, Any], patch: dict[str, Any], fields: set[str]
    ) -> dict[str, Any]:
        """The call-shape fields this patch sets, validated as add validates them; nothing is applied here."""
        sent = {k: patch.get(k) for k in CALL_SHAPE if k in fields}
        if not sent:
            return {}
        if o["executor"] != "http":
            raise ValidationFailed(f"{o['name']} is not an HTTP operation; its call comes from its server or seed.")
        for k in ("method", "path", "headers"):
            if k in sent and sent[k] is None:
                raise ValidationFailed(f"An HTTP operation keeps a {k}.")
        if "path" in sent:
            path = str(sent["path"]).strip()
            if not path.startswith("/"):
                raise ValidationFailed("Enter the path after the module endpoint, starting with /.")
            if not m["endpoint"]:
                raise ValidationFailed("Set the module's endpoint before editing a path.")
            sent["path"] = self._split_url(m["endpoint"].rstrip("/") + path, m["endpoint"])[1]
        if "headers" in sent:
            sent["headers"] = self._checked_headers(cast(list[dict[str, str]], sent["headers"]))
        if "body" in sent:
            sent["body"] = (sent["body"] or "").strip() or None
            if problem := self._body_problem(sent["body"]):
                raise ValidationFailed(problem)
        if "response_transform" in sent:
            sent["response_transform"] = (sent["response_transform"] or "").strip() or None
            if sent["response_transform"] and (problem := transform.problem(sent["response_transform"])):
                raise ValidationFailed(problem)
        limit = sent.get("timeout_ms")
        if limit is not None and not 1_000 <= limit <= 120_000:
            raise ValidationFailed("Set a timeout between 1 and 120 seconds (1000 to 120000 ms).")
        return {k: v for k, v in sent.items() if v != o.get(k)}

    @staticmethod
    def _shape_changes(o: dict[str, Any], shape: dict[str, Any]) -> list[dict[str, Any]]:
        """Applies a validated call-shape edit to `o` and says what changed. A new method, path or body changes the
        contract a workflow was approved against, so it is major; headers, the transform and the timeout are minor."""
        if not shape:
            return []
        name = o["name"]
        out: list[dict[str, Any]] = []
        contract = [k for k in ("method", "path", "body") if k in shape]
        if contract:
            before = f"{o['method']} {o['path']}"
            after = f"{shape.get('method', o['method'])} {shape.get('path', o['path'])}"
            detail = f"Call {before} → {after}" if before != after else "Call unchanged"
            if "body" in shape:
                detail += "; body edited"
            out.append({"operation": name, "kind": "schema_changed", "detail": detail, "major": True})
        minor: list[str] = []
        if "headers" in shape:
            minor.append("Headers edited")
        if "response_transform" in shape:
            minor.append("Response transform " + ("set" if shape["response_transform"] else "removed"))
        if "timeout_ms" in shape:
            limit = shape["timeout_ms"]
            minor.append(f"Timeout {limit / 1000:g} s" if limit else "Timeout back to the module's")
        if minor:
            out.append({"operation": name, "kind": "settings", "detail": "; ".join(minor), "major": False})
        o.update(shape)
        # A placeholder the new path or body names becomes an input; fields nothing names stay, and the console warns.
        named = [*URL_VAR.findall(o["path"] or ""), *BODY_VAR.findall(o.get("body") or "")]
        have = {f["name"] for f in o["input"]}
        o["input"] = [*o["input"], *(_sample_field(n) for n in dict.fromkeys(named) if n not in have)]
        return out

    @staticmethod
    def _field_list(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The input fields as stored: trimmed text, and unset optional parts left out."""
        out: list[dict[str, Any]] = []
        for f in fields:
            row: dict[str, Any] = {"name": str(f["name"]).strip(), "type": f["type"], "required": bool(f["required"])}
            for k in ("description", "format", "example"):
                if f.get(k) not in (None, ""):
                    row[k] = str(f[k]).strip()
            if f.get("enum"):
                row["enum"] = [str(v).strip() for v in f["enum"]]
            if f.get("default") is not None:
                row["default"] = f["default"]
            out.append(row)
        return out

    @staticmethod
    def _check_input(
        o: dict[str, Any],
        fields: list[dict[str, Any]],
        *,
        path: str | None,
        body: str | None,
        binding: dict[str, Any] | None,
    ) -> None:
        """Refuses an input schema the call could not use, naming the field (details.field `input.<name>`)."""

        def refuse(name: str, message: str) -> Unprocessable:
            return Unprocessable(message, details={"field": f"input.{name}"})

        seen: set[str] = set()
        for f in fields:
            name = f["name"]
            if not FIELD_NAME.match(name):
                raise refuse(name, f"{name or 'A field'}: use letters, digits and underscores, starting with a letter.")
            if name in seen:
                raise refuse(name, f"{name} is listed twice.")
            seen.add(name)
            enum = f.get("enum")
            if enum is not None:
                if f["type"] != "string":
                    raise refuse(name, f"{name}: only a string field takes a list of allowed values.")
                if any(not v for v in enum) or len(set(enum)) != len(enum):
                    raise refuse(name, f"{name}: allowed values must be distinct and not empty.")
            if "default" in f:
                value = f["default"]
                allowed = DEFAULT_TYPES.get(f["type"])
                if f["required"]:
                    raise refuse(name, f"{name} is required, so a call always sends it; a default would never apply.")
                if (
                    allowed is None
                    or not isinstance(value, allowed)
                    or (isinstance(value, bool) and f["type"] != "boolean")
                ):
                    raise refuse(name, f"{name}: the default must be of type {f['type']}.")
                if enum is not None and value not in enum:
                    raise refuse(name, f"{name}: the default {value} is not one of its allowed values.")
        if binding and binding["arg"] not in seen:
            raise refuse(
                binding["arg"],
                f"{binding['arg']} is bound to {binding['bindTo']}; remove the binding before removing the field.",
            )
        named = [*URL_VAR.findall(path or ""), *BODY_VAR.findall(body or "")]
        for n in named:
            if n not in seen:
                raise refuse(
                    n, f"The call uses {{{n}}}, which is not an input of {o['name']}; add it or change the call."
                )
        if o.get("amount_max") is not None and o["access"] == "write" and "amount" not in seen:
            raise refuse("amount", "The amount limit reads the amount input; remove the limit before removing it.")

    @staticmethod
    def _input_changes(o: dict[str, Any], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """What an input edit changes for the agent. A field it must now send, a field taken away, a type change or a
        changed list of allowed values or a changed default changes the contract callers were approved against, so it is
        major; a new optional field without a default, a field made optional, a description or example is minor."""
        name = o["name"]
        before = {f["name"]: f for f in o["input"]}
        after = {f["name"]: f for f in fields}
        major: list[str] = []
        minor: list[str] = []
        for n, f in after.items():
            old = before.get(n)
            if old is None:
                # A new optional field with a default changes what calls send, so it is reviewed like a required one.
                grows = f["required"] or f.get("default") is not None
                (major if grows else minor).append(f"{n} added{' (required)' if f['required'] else ''}")
                continue
            if old["type"] != f["type"]:
                major.append(f"{n} {old['type']} → {f['type']}")
            if not old.get("required") and f["required"]:
                major.append(f"{n} now required")
            elif old.get("required") and not f["required"]:
                minor.append(f"{n} now optional")
            if (old.get("enum") or None) != (f.get("enum") or None):
                major.append(f"{n} allowed values changed")
            if old.get("default") != f.get("default"):
                major.append(f"{n} default {old.get('default')!r} → {f.get('default')!r}")
            if any(old.get(k) != f.get(k) for k in ("description", "format", "example")):
                minor.append(f"{n} edited")
        major.extend(f"{n} removed" for n in before if n not in after)
        out: list[dict[str, Any]] = []
        if major:
            out.append({"operation": name, "kind": "schema_changed", "detail": "; ".join(major), "major": True})
        elif minor:
            out.append({"operation": name, "kind": "schema_changed", "detail": "; ".join(minor), "major": False})
        if not major and not minor and [f["name"] for f in o["input"]] != list(after):
            out.append({"operation": name, "kind": "schema_changed", "detail": "Fields reordered", "major": False})
        return out

    async def publish(self, who: Caller, module_id: str, note: str) -> dict[str, Any]:
        _can(who, "tools", "publish", what="tool modules", security_team=self.security_team)
        m = await self._find(who, module_id)
        reviewed_change = _differs_from_published(m)
        if not m["pending"] and not reviewed_change:
            raise ValidationFailed("There are no changes to publish.")
        if not note.strip():
            raise ValidationFailed("Say what changed.")
        _refuse_during_review(m, "publish another version")
        major = reviewed_change or any(c["major"] for c in m["pending"])
        # "always" sends every version to a review; "major" and "never" send a major one only, since every major
        # change to a tool module touches what it calls, how a write is approved, or where it reaches (c-139).
        mode = (
            await self.publish_policy.mode(who.tenant_id, m["team_id"]) if self.publish_policy else ToolsMode("major")
        )
        waits = major or mode.mode == "always"
        if not m["pending"]:
            # Edits a declined version left in place: sent to Security again as they stand.
            m["pending"] = [
                {"operation": "*", "kind": "settings", "detail": "Changes Security declined, sent again", "major": True}
            ]
        a, b = (int(x) for x in m["version"].split(".")[:2])
        version = f"{a + 1}.0.0" if major else f"{a}.{b + 1}.0"
        now = self.clock()
        if not waits:
            m["versions"] = [{**v, "status": "deprecated"} if v["status"] == "published" else v for v in m["versions"]]
        m["versions"] = [
            *m["versions"],
            {
                "id": f"{m['id']}_v{version}",
                "version": version,
                "major": major_of(version),
                "status": "in_review" if waits else "published",
                "published_at": None if waits else now,
                "published_by": who.name,
                "note": note.strip(),
                "changes": m["pending"],
                "pinned_by": [],
                "reachability": [{"environment": "test", "ok": True, "checkedAt": now.isoformat()}],
                "review_required": waits,
                "policy": "always" if mode.unreadable else mode.mode,
            },
        ]
        if waits:
            # A major change is the Security team's to decide; a minor one waiting under "always" is the module's team.
            review_id = await self._open_review(
                who, m, version, cast(list[dict[str, Any]], m["versions"][-1]["changes"]), note, security=major
            )
            m["versions"][-1].update(review_id=review_id, requested_at=now)
        # A major version waits for Security: until it approves, calls keep the published call shape and approval policy
        # (the baseline), so a loosened policy or a new path does not run in the meantime.
        m.update(version=version, pending=[], baseline=m["baseline"] if waits else None)
        return await self._detail(await self._save(m), who.team, who)

    async def _open_review(
        self,
        who: Caller,
        m: Aggregate,
        version: str,
        changes: list[dict[str, Any]],
        note: str,
        *,
        security: bool = True,
    ) -> str:
        """Opens the version's review in agents-service's Reviews as the person asking; its id. Raises when it cannot
        open, before anything is saved, so no version waits for a review that does not exist."""
        if self.reviews is None:
            raise ServiceUnavailable("Reviews is not configured, so no review can open.", code="reviews_unavailable")
        return await self.reviews.open(
            who.credentials,
            tenant_id=who.tenant_id,
            team_id=who.team.id,
            module=m,
            version=version,
            changes=changes,
            note=note.strip(),
            security=security,
        )

    async def discard(self, who: Caller, module_id: str) -> dict[str, Any]:
        _can(who, "tools", "edit", what="tool modules", security_team=self.security_team)
        m = await self._changeable(who, module_id)
        _refuse_during_review(m, "discard changes")
        if m["baseline"] is None:
            raise ValidationFailed("There are no changes to discard.")
        m.update(operations=copy.deepcopy(m["baseline"]), pending=[], baseline=None)
        return await self._detail(await self._save(m), who.team, who)

    async def request_review(self, who: Caller, module_id: str, note: str) -> dict[str, Any]:
        _can(who, "tools", "publish", what="tool modules", security_team=self.security_team)
        m = await self._find(who, module_id)
        if any(v["status"] == "in_review" for v in m["versions"]):
            raise Conflict("A security review is already open for this module.")
        if not m["operations"]:
            raise Unprocessable("Add at least one operation before requesting a security review.")
        last = m["versions"][-1]
        changes = last["changes"] or [{"operation": "*", "kind": "settings", "detail": "First review", "major": True}]
        review_id = await self._open_review(who, m, m["version"], changes, note)
        if m["status"] == "draft":
            m["status"] = "in_review"
        reviewed = {"review_id": review_id, "requested_at": self.clock(), "finding": None, "reviewer": None}
        status = "in_review" if last["status"] == "draft" else last["status"]
        m["versions"] = [*m["versions"][:-1], {**last, **reviewed, "status": status}]
        return await self._detail(await self._save(m), who.team, who)

    async def apply_decision(
        self,
        tenant_id: str,
        module_id: str,
        *,
        request_id: str,
        version: str,
        decision: str,
        reason: str | None,
        by: str | None,
    ) -> dict[str, Any]:
        """A decision made in Reviews, sent by agents-service (c-163), which already held it to the review rules: not
        the requester, not the saver, Security for a security change, a reason for a no. Approving the module's
        current version publishes it and clears drift, since the reviewed tool list is the one now held; a no sends a
        module never published back to draft, and withdraws the declined version of a published one. Applying the same
        decision twice changes nothing."""
        m = await self.store.get_any(tenant_id, module_id)
        if m is None:
            raise NotFound("Module")
        v = next((x for x in m["versions"] if x["version"] == version and x.get("review_id") == request_id), None)
        if v is None:
            raise NotFound("Review")
        if v["status"] != "in_review":
            return await self._detail(m, self.dir.everyone)
        now = self.clock()
        v.update(reviewer=by, finding=None if decision == "approved" else (reason or "").strip() or None)
        current = version == m["version"]
        if decision == "approved" and current:
            for x in m["versions"]:
                if x["status"] == "published":
                    x["status"] = "deprecated"
            v.update(status="published", published_at=now)
            m.update(status="published", drift=False)
            if not m["pending"]:
                # The reviewed operations are now the published ones; edits staged since keep the baseline.
                m["baseline"] = None
        elif decision != "approved" and current:
            if m["status"] == "in_review":
                m["status"] = "draft"
                v["status"] = "draft"
            else:
                v["status"] = "revoked"
        return await self._detail(await self._save(m), self.dir.everyone)

    # ── Workflow approvals ────────────────────────────────────────────────

    async def request_approval(self, who: Caller, module_id: str, i: dict[str, Any]) -> dict[str, Any]:
        _can(who, "tools", "edit", what="tool modules", security_team=self.security_team)
        m = await self._find(who, module_id)
        if m["status"] == "draft":
            raise Conflict("Submit the module for security review before workflows can request it.")
        wf = (await self.workflows.all(who.tenant_id)).get(i["workflow_id"])
        if wf is None:
            raise ValidationFailed("Choose a workflow.")
        if not wf.team_id:
            # Fail closed: a workflow no team owns has no one the grant would be for.
            raise Unprocessable(f"{wf.name} belongs to no team, so no team can be granted access for it.")
        # The workflow's platform team, which the dev seed need not hold (c-423): the grant is for that team id.
        owner = self.dir.team(wf.team_id)
        if not i["operations"]:
            raise ValidationFailed("Choose at least one operation.")
        # The default policy: the module's team decides, unless an operation asked for names its own approving team.
        decider = next(
            (o["approver_team"] for o in m["operations"] if o["name"] in i["operations"] and o.get("approver_team")),
            m["team_id"],
        )
        if decider is None:
            # A workspace-level module (the platform's tools, c-433) serves every team's runs with no grant, and no team
            # would decide a request for it (c-439).
            raise Unprocessable(
                f"{m['display_name']} belongs to no team: every team's workflows may already use it, so there is "
                "nothing to request."
            )
        production = i["environment"] == "production"
        most = 365 if production else 90
        if not 1 <= i["expires_in_days"] <= most:
            raise ValidationFailed(f"{'Production' if production else 'Test'} approvals last at most {most} days.")
        if len(i["justification"].strip()) < 10:
            raise ValidationFailed("Explain why the workflow needs these operations.")
        name = wf.name
        if any(a["workflow_id"] == i["workflow_id"] and a["status"] == "requested" for a in self._approvals(m)):
            raise Conflict(f"{name} already has an open request for this module.")
        now = self.clock()
        approval_id = new_id("apr")
        a: dict[str, Any] = {
            "id": approval_id,
            "workflow_id": i["workflow_id"],
            "workflow_name": name,
            "workflow_team_id": owner.id,
            "environment": i["environment"],
            "major": major_of(m["version"]),
            "operations": i["operations"],
            "constraints": None,
            "requested_by": who.name,
            # Who asked, as the token names them: the requester rule compares it, never the display name.
            "requested_by_email": who.principal.email if who.principal else None,
            "justification": i["justification"].strip(),
            "requested_at": now,
            "decided_by": None,
            "decided_at": None,
            "status": "requested",
            "expires_at": now + timedelta(days=i["expires_in_days"]),
            "reason": None,
            # Decided in Human Tasks (c-166) by `decider`; who in that team may decide is can(reviews.decide), as for
            # any review.
            "decider_team": decider,
            # The system workflow's run key (c-257): the module page opens its review in Human Tasks by it.
            "review_id": f"{ACCESS_REQUESTED}:{approval_id}",
        }
        m["approvals"] = [*m["approvals"], a]
        await self._save(m, touch=False, events=[access_event(m, a)])
        return self._approval_out(a)

    async def apply_access_decision(
        self,
        tenant_id: str,
        module_id: str,
        *,
        approval_id: str,
        decision: str,
        reason: str | None,
        by: str | None,
        team_id: str | None = None,
        deciders: Sequence[str] = (),
    ) -> dict[str, Any]:
        """A tool access review's decision from Human Tasks (c-166), applied to the module's approval: approved grants
        it, anything else ends the request. Applying the same decision again changes nothing; a request already ended
        another way (revoked, or decided otherwise) is refused, so a late approval never revives a revoked grant."""
        m = await self.store.get_any(tenant_id, module_id)
        if m is None:
            raise NotFound("Tool module")
        a = next((x for x in m["approvals"] if x["id"] == approval_id), None)
        if a is None:
            raise NotFound("Approval")
        if team_id is not None and a.get("decider_team") not in (None, team_id):
            # The system workflow runs in the deciding team (c-257); a run in another team decides nothing here.
            raise Forbidden("This request is decided by another team.", code="team_forbidden")
        asker = str(a.get("requested_by_email") or "").lower()
        if asker and asker in {str(d).lower() for d in (*deciders, by or "")}:
            # Separation of duties follows the tenant's requesterMayDecide (c-186), as every other decision does: the
            # asker decides their own request only while it is on.
            allowed = self.requester_policy is not None and await self.requester_policy.allowed(tenant_id)
            if not allowed:
                raise Forbidden("The person who asked for this access cannot decide it.", code="requester_decides")
        status = "approved" if decision == "approved" else "rejected"
        if a["status"] == status:
            return self._approval_out(a)
        if a["status"] != "requested":
            raise Conflict(f"This request was already {a['status']}.", code="already_decided")
        a.update(status=status, decided_by=by, decided_at=self.clock(), reason=(reason or "").strip() or None)
        await self._save(m, touch=False)
        return self._approval_out(a)

    async def decide_approval(
        self, who: Caller, module_id: str, approval_id: str, decision: str, reason: str | None
    ) -> dict[str, Any]:
        m = await self._find(who, module_id)
        a = next((x for x in m["approvals"] if x["id"] == approval_id), None)
        if a is None:
            raise NotFound("Approval")
        if a.get("review_id"):
            # Decided in Human Tasks with every other review (c-166); this route only ends requests made before then.
            raise Conflict(f"Decide this request in Human Tasks ({a['review_id']}).", code="decided_in_reviews")
        _can(
            who,
            "tools",
            "decide",
            what="this module approval",
            security_team=self.security_team,
            requested_by=(a.get("requested_by_email"),),
        )
        if a["status"] != "requested":
            raise Conflict("This request was already decided.")
        if decision == "rejected" and not (reason or "").strip():
            raise ValidationFailed("Give a reason for the rejection.")
        a.update(status=decision, decided_by=who.name, decided_at=self.clock(), reason=(reason or "").strip() or None)
        await self._save(m, touch=False)
        return self._approval_out(a)

    async def revoke_approvals(self, who: Caller, module_id: str, ids: list[str], reason: str) -> dict[str, Any]:
        _can(who, "tools", "decide", what="module approvals", security_team=self.security_team)
        m = await self._find(who, module_id)
        if not reason.strip():
            raise ValidationFailed("Give a reason.")
        out: dict[str, Any] = {"updated": [], "skipped": []}
        for approval_id in ids:
            a = next((x for x in m["approvals"] if x["id"] == approval_id), None)
            if a is None:
                out["skipped"].append({"id": approval_id, "reason": "Not found"})
                continue
            s = self._approval_status(a)
            if s not in ("approved", "requested"):
                out["skipped"].append(
                    {"id": approval_id, "reason": "Already expired" if s == "expired" else f"Already {s}"}
                )
                continue
            a.update(status="revoked", reason=reason.strip(), decided_by=who.name, decided_at=self.clock())
            out["updated"].append(approval_id)
        if out["updated"]:
            await self._save(m, touch=False)
        return out

    # ── Test console ──────────────────────────────────────────────────────

    async def test(self, who: Caller, module_id: str, i: dict[str, Any]) -> dict[str, Any]:
        """What the gateway would decide for this call in this run context, and the answer when it allows: on the
        sandbox target a read is the real call, through the same executor and egress policy as /v1/calls, on the
        published call shape; a write answers from the stub (`stubbed`), so the test console never writes to a system.
        A test call is not a gateway call: it spends no rate and is not in the executions log. The `owner` context is
        the module's own team trying it (whoever passes the module's team guard): no workflow approval is needed,
        reads run for real, writes answer from the stub, and a bound field takes the value typed (c-048 T008)."""
        if who.principal is not None and who.principal.kind == "api_key":
            # A key's tools.run is for the gateway's call path over MCP (c-356), which logs and limits each call; the
            # test console is a person's, and its reads are neither logged nor rate limited.
            raise Forbidden("An API key runs tools over MCP, not the test console.", code="role_required")
        _can(who, "tools", "run", what="tool modules", security_team=self.security_team)
        m = await self._find(who, module_id)
        o = next((x for x in m["operations"] if x["name"] == i["operation"]), None)
        if o is None:
            raise NotFound("Operation")
        owner = i["context_id"] == OWNER_CONTEXT
        ctx = None if owner else next((c for c in self._run_contexts(m, who.team) if c["id"] == i["context_id"]), None)
        if ctx is None and not owner:
            raise ValidationFailed("Choose a run context.")
        call_id = new_id("test")
        sandbox = i["target"] == "sandbox"

        def deny(reason: str) -> dict[str, Any]:
            return {
                "decision": "deny",
                "denyReason": reason,
                "denyMessage": DENY_TEXT[reason],
                "status": 403,
                "latencyMs": 0,
                "bound": [],
                "wouldPause": False,
                "output": {"error": reason, "message": DENY_TEXT[reason]},
                "masked": [],
                "callId": call_id,
            }

        if not o["enabled"]:
            return deny("operation_hidden")
        if m["status"] != "published" and sandbox:
            return deny("module_not_published")
        if m["status"] == "published" and ctx is not None:
            mine = [a for a in self._approvals(m) if a["workflow_id"] == ctx["workflowId"]]
            active = [a for a in mine if a["status"] == "approved"]
            if not active:
                return deny("approval_expired" if any(a["status"] == "expired" for a in mine) else "no_approval")
            if not any(o["name"] in a["operations"] for a in active):
                return deny("operation_not_approved")
        args = dict(i["input"])
        bound: list[dict[str, Any]] = []
        b = o["binding"]
        if b:
            value = (ctx or {}).get("bindings", {}).get(b["bindTo"]) if ctx else None
            source = b["bindTo"]
            if not value and (ctx is None or ctx["caseId"] == SAMPLE_CASE):
                # The owner, or a sample context, has no case: the value typed stands in for it, marked as a sample.
                value, source = args.get(b["arg"]), "sample"
            if not value:
                if b["required"]:
                    return deny("subject_unbound")
            else:
                given = args.get(b["arg"])
                if given not in (None, "") and given != value and b["mode"] == "equals":
                    return deny("subject_mismatch")
                args[b["arg"]] = value
                bound.append({"arg": b["arg"], "value": value, "source": source})
        missing = [f["name"] for f in o["input"] if f["required"] and args.get(f["name"]) in (None, "")]
        if missing:
            return {
                "decision": "invalid",
                "status": 422,
                "latencyMs": 0,
                "bound": bound,
                "wouldPause": False,
                "invalid": [{"field": f, "message": "Required."} for f in missing],
                "output": {"error": "invalid_input", "missing": missing},
                "masked": [],
                "callId": call_id,
            }
        if amount_refusal(o, args) is not None:  # the gateway's own check (ops_tools.limits)
            return deny("constraint")
        would_pause = o["access"] in WRITES and o["requires_approval"]
        # The owner's write answers from the stub, so there is nothing for an approval to guard.
        if would_pause and sandbox and ctx is not None and not i.get("simulate_approval"):
            return deny("approval_token_missing")
        # The workbench's draft transform and mock run in place of the operation's for this test only (c-088): nothing
        # is staged, so what agents get changes only through staging and publishing.
        draft: dict[str, Any] = i.get("draft") or {}
        if "stub" in draft and len(json.dumps(draft["stub"])) > MAX_STUB_BYTES:
            raise ValidationFailed(f"Keep the mock response under {MAX_STUB_BYTES // 1000} KB.")
        template = draft["response_transform"] if "response_transform" in draft else o.get("response_transform")
        mock = draft["stub"] if "stub" in draft and draft["stub"] is not None else o["stub"]
        trial = Trial()
        trial.note("Input checked against the operation's schema")
        out: dict[str, Any] = {
            "decision": "allow",
            "status": 200,
            "latencyMs": 0,
            "bound": bound,
            "wouldPause": would_pause,
            "output": masked(mock, o["masked_output"]),
            "masked": o["masked_output"],
            "callId": call_id,
        }
        if would_pause and i.get("simulate_approval"):
            out["testApprovalToken"] = new_id("test-apt")
        if sandbox and o["access"] in WRITES:
            out["stubbed"] = True
        answer = await self.mocks.for_call(who.tenant_id, o["name"], args, TEST) if "stub" not in draft else None
        if sandbox and o["access"] not in WRITES and o.get("executor") in ("http", "mcp") and self.egress is not None:
            if self.http is not None:
                out.update(await self._real_read(m, o, args, i.get("secret_values"), trial))
        elif answer is not None:
            # A mock answer the test environment holds for this input (c-332), as a test run would get it.
            await self.mocks.wait(answer, o.get("timeout_ms") or m["timeout_ms"])
            status = 504 if answer["timeout"] else int(answer["status"])
            out.update(status=status, output=masked(answer.get("body"), o["masked_output"]), mockId=answer["id"])
            trial.note(f"Answered from the mock answer {answer['name']}")
        else:
            trial.note("Answered from the mock response")
        raw = out["output"]
        out["rawResponse"] = raw
        if template and out["status"] < 400:
            shaped, failed = await transform.apply(template, raw)
            # After the transform, as the gateway scrubs after its own: a template can repeat what it was given.
            out["output"] = scrub(shaped, trial.used)
            if failed is not None:
                out["transformError"] = scrub(failed, trial.used)
                trial.note("Transform failed; the raw response is returned")
            else:
                trial.note("Draft transform applied" if "response_transform" in draft else "Transform applied")
        if trial.request is not None:
            out["request"] = trial.request
        out["log"] = [{"atMs": at, "message": message} for at, message in trial.log]
        return out

    async def _real_read(
        self,
        module: dict[str, Any],
        op: dict[str, Any],
        args: dict[str, Any],
        secret_values: dict[str, str] | None,
        trial: Trial,
    ) -> dict[str, Any]:
        """The read the gateway would run: the published call shape (a staged edit runs only once published), the
        module's egress policy, its secrets and masks. Its latency and host are the real call's. The answer comes back
        before any transform; the caller applies the draft's. `secret_values` stand in for the tenant's secrets they
        name, for this call only: they are not stored, logged or returned (the request is scrubbed of them)."""
        found = await self.store.operation_named(module["tenant_id"], op["name"], module.get("team_id"))
        if found is not None:
            module, op = found
        assert self.egress is not None and self.http is not None
        runner = (HttpExecutor if op["executor"] == "http" else McpExecutor)(
            self.http, self.egress, self.secrets, self.auth
        )
        started = time.perf_counter()
        outcome = await runner.run(
            module,
            op,
            with_defaults(op["input"], args),
            actor="test-console",
            secret_values=secret_values,
            trial=trial,
            # Try it answers from the test system (owner, 2026-10-19: everything but live runs uses test).
            environment=TEST,
        )
        result: dict[str, Any] = {
            "output": outcome.output,
            "latencyMs": round((time.perf_counter() - started) * 1000),
            "reachedHost": urlsplit(str(module["endpoint"])).hostname,
            "stubbed": False,
        }
        if not outcome.ok:
            error = cast(dict[str, Any], cast(dict[str, Any], outcome.output).get("error") or {})
            # The upstream's own status when it answered; otherwise the gateway's, by whether the call timed out.
            result["status"] = error.get("status") or (504 if "TIMEOUT" in str(error.get("code")) else 502)
        return result

    # ── Not in this card ──────────────────────────────────────────────────

    async def _connection_ok(self, tenant_id: str, connection_id: str | None) -> None:
        if not connection_id:
            return
        conn = await self.connections.get(tenant_id, connection_id)
        if conn is None:
            raise ValidationFailed("That connection no longer exists. Pick another one.")
        if status_of(conn, self.clock()) == "revoked":
            raise Conflict(f"{conn['name']} is revoked. Reconnect it in Connections first.")

    async def _fetch(self, who: Caller, url: str) -> bytes:
        """GETs `url` through the egress policy: https to a listed host, connected only at a checked address."""
        if self.egress is None or self.http is None:
            raise NotYetAvailable("This service has no egress policy, so it fetches nothing.")
        try:
            host = await self.egress.check_url(who.tenant_id, url)
            res = await self.http.get(url, timeout=10, extensions=for_tenant(who.tenant_id))
        except EgressDenied as e:
            raise ValidationFailed(str(e), code="egress_denied") from e
        except httpx.HTTPError as e:
            raise UpstreamUnavailable(f"{urlsplit(url).hostname} could not be reached ({type(e).__name__}).") from e
        if res.status_code >= 400:
            raise UpstreamUnavailable(f"{host} answered {res.status_code} for the document.")
        if len(res.content) > MAX_SPEC_BYTES:
            raise Unprocessable(f"The document from {host} is larger than {MAX_SPEC_BYTES // 1_000_000} MB.")
        return res.content

    async def _discover(self, who: Caller, source: dict[str, Any]) -> dict[str, Any]:
        await self._connection_ok(who.tenant_id, source.get("connection_id"))
        if source["kind"] == "openapi":
            if not source.get("spec_url"):
                if source.get("file_id") or source.get("file_name"):
                    raise NotYetAvailable("Importing an uploaded document is not available yet; give its URL.")
                raise ValidationFailed("Add the spec as a URL.")
            raw = await self._fetch(who, source["spec_url"])
            try:
                text = raw.decode()
                spec: Any = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
                return openapi.discover(spec, source["spec_url"])
            except (UnicodeDecodeError, ValueError, yaml.YAMLError) as e:
                raise ValidationFailed(f"The document could not be read: {e}"[:300]) from e
        if not source.get("url"):
            raise ValidationFailed("Enter the MCP server's https address.")
        return await self._discover_mcp(who, source["url"], source.get("connection_id"))

    async def _signed_in_headers(self, who: Caller, connection_id: str | None, url: str) -> tuple[dict[str, str], Any]:
        """A discovery's sign-in through the named connection, in the test environment (c-331): its headers and its
        client certificate; nothing for no connection."""
        if not connection_id or self.auth is None:
            return {}, None
        probe = {"tenant_id": who.tenant_id, "connection_id": connection_id, "team_id": who.team.id, "endpoint": url}
        try:
            prepared = await self.auth.prepare(probe, TEST, tool="discovery", actor=who.name)
        except AuthFailed as e:
            raise ValidationFailed(
                str(e), code="sign_in_required" if e.code == "NOT_SIGNED_IN" else "connection"
            ) from e
        return (prepared.headers, prepared.certificate) if prepared else ({}, None)

    async def _discover_mcp(self, who: Caller, url: str, connection_id: str | None = None) -> dict[str, Any]:
        if self.egress is None or self.http is None:
            raise NotYetAvailable("This service has no egress policy, so it reaches no MCP server.")
        headers, certificate = await self._signed_in_headers(who, connection_id, url)
        try:
            await self.egress.check_url(who.tenant_id, url)
            session = mcp.McpSession(self.http, url, tenant_id=who.tenant_id, headers=headers, certificate=certificate)
            server = await session.initialize()
            tools = await session.list_tools()
        except EgressDenied as e:
            raise ValidationFailed(str(e), code="egress_denied") from e
        except mcp.McpError as e:
            if e.status == 401:
                raise ValidationFailed(
                    f"{urlsplit(url).hostname} needs sign-in before it lists its tools. Add it as a connection and "
                    "sign in.",
                    code="sign_in_required",
                ) from e
            raise UpstreamUnavailable(f"{urlsplit(url).hostname}: {e}") from e
        return mcp.discovered(tools, url, server)

    @staticmethod
    def _public(result: dict[str, Any]) -> dict[str, Any]:
        """The console's DiscoveryResult: an operation's headers stay on the service until import."""
        ops = [
            {k: v for k, v in o.items() if k not in ("headers", "stub", "output_shape", "response_schema")}
            for o in result["operations"]
        ]
        return {**result, "operations": ops}

    async def discover(self, who: Caller, source: dict[str, Any]) -> dict[str, Any]:
        _can(who, "tools", "create", what="tool modules", security_team=self.security_team)
        return self._public(await self._discover(who, source))

    @staticmethod
    def _chosen(found: dict[str, Any], chosen: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The caller's picks as the source describes them: name and the confirmed access class from the caller,
        everything else from the source. A name the source does not list is refused."""
        listed = {o["name"]: o for o in found["operations"]}
        unknown = [o["name"] for o in chosen if o["name"] not in listed]
        if unknown:
            raise ValidationFailed(f"{', '.join(unknown)} is not in the source.")
        executor = "mcp" if found["type"] == "mcp" else "http"
        return [{**listed[o["name"]], "access": o["access"], "executor": executor} for o in chosen]

    async def import_operations(self, who: Caller, module_id: str, i: dict[str, Any]) -> dict[str, Any]:
        """Appends the chosen operations as the source describes them now; the caller picks which, and confirms each
        one's access class, but never supplies their method, path, inputs or headers."""
        _can(who, "tools", "create", what="tool modules", security_team=self.security_team)
        m = await self._changeable(who, module_id)
        chosen: list[dict[str, Any]] = i["operations"]
        if not chosen:
            raise ValidationFailed("Choose at least one operation to import.")
        found = await self._discover(who, {"connection_id": m["connection_id"], **_given(i["source"])})
        fresh = [o for o in self._chosen(found, chosen) if not any(x["name"] == o["name"] for x in m["operations"])]
        if not fresh:
            raise Conflict("Every chosen operation is already in this module.")
        if m["endpoint"] and m["endpoint"].rstrip("/") != found["endpoint"]:
            raise Conflict(f"This module calls {m['endpoint']}; the source serves {found['endpoint']}.")
        m["endpoint"] = found["endpoint"]
        if found["type"] == "mcp":
            # A tool the server no longer lists is drift from what was reviewed: calls to it may now do anything.
            servers_names = {o["path"] for o in found["operations"]}
            m["drift"] = any(o["executor"] == "mcp" and o["path"] not in servers_names for o in m["operations"])
        endpoint: str = found["endpoint"]
        host = urlsplit(endpoint).hostname
        if host and host not in m["egress_hosts"]:
            m["egress_hosts"] = [*m["egress_hosts"], host]
        await self._append(who, m, fresh)
        return await self._detail(await self._save(m), who.team, who)


def _review_open(m: Aggregate) -> bool:
    """A version waits for review, or the newest one was declined and nothing has passed review since."""
    if any(v["status"] == "in_review" for v in m["versions"]):
        return True
    last = m["versions"][-1] if m["versions"] else None
    return bool(last and last.get("finding") and last["status"] in ("draft", "revoked"))
