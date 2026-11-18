"""The tool-module registry's rules: the console's tool-modules contract, served from the database.

Each rule is ported from the console's mock (apps/console/src/lib/api/mock/tool-modules/index.ts), which remains the
specification: approval state, views and facets, staged changes and major versus minor publishes, security reviews,
workflow approvals with expiry that the requester never decides, the refusal of literal credentials, and the test
console's deny reasons. A method reads the module aggregate, changes it, and writes it back against the revision it
read, so two concurrent edits cannot overwrite each other.

Not here yet: discovery and import from OpenAPI or MCP, auditing to platform-service, and granting approved
operations to a workflow's agent (agents-service owns grants).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NotRequired, TypedDict, cast
from urllib.parse import urlsplit

import httpx
import yaml
from pydantic import JsonValue

from ops_access import ANY_TEAM, Access, require_provisioner
from ops_identity import Principal
from ops_service_kit import narrow
from ops_service_kit.errors import (
    ApiError,
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    Unprocessable,
    ValidationFailed,
)
from ops_service_kit.http import Json
from ops_service_kit.ids import new_id
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.listing import ListPage

from .. import mcp, transform
from ..auth import Authenticator, AuthFailed, may_use
from ..connections.records import (
    ConnectionView,
    auth_of,
    connection_base,
    module_auth,
    ref_of,
    sign_in_of,
    status_of,
)
from ..egress import EgressDenied, EgressPolicy, egress_client, for_tenant
from ..environments import TEST
from ..executor import ConsoleRan, ConsoleRefused, Trial, masked, secret_names
from ..held_hosts import HostHeld, refused
from ..limits import amount_refusal
from ..mocks import MockAnswers
from ..registry import approval_policy
from ..secrets import SecretResolver, scrub
from ..store.calls import CallLog, CallStats, DayStats, GatewayCall
from ..store.connections import Account, ConnectionStore
from ..store.mocks import MockStore
from ..store.module_list import ModuleList, Window
from ..store.modules import (
    APPROVAL,
    REVIEWED,
    Aggregate,
    Approval,
    Binding,
    Change,
    CodeSettings,
    Header,
    HostNotAllowedError,
    InputField,
    Module,
    ModuleColumns,
    ModuleGrants,
    ModuleRef,
    ModuleStore,
    Operation,
    PinnedBy,
    Reachability,
    ServiceEvent,
    StaleModuleError,
    StoredOperation,
    TitleOf,
    Version,
    grant_views,
    operation_defaults,
    restored_operation,
    version_defaults,
)
from ..store.modules import (
    published as published_operations,
)
from . import openapi
from .directory import Directory, Team, owns_module
from .discovered import Discovered, DiscoveredOperation, PublicDiscovered, PublicOperation
from .executions import CallRowJson, DayJson, ModuleActivityJson, call_row
from .policy import PublishPolicy, RequesterMayDecide, ToolsMode, WriteApprovals, own_request_refusal, tool_mode
from .review_events import ACCESS_REQUESTED, access_event, policy_changed_event
from .reviews import ReviewOpener
from .schemas import (
    ApprovalRequestIn,
    BlankModuleIn,
    CodeOperationIn,
    CodeSettingsIn,
    DiscoveredOperationIn,
    HttpOperationIn,
    ImportOperationsIn,
    ModuleDetailsPatchIn,
    ModuleIn,
    ModuleSourceIn,
    ModuleTestIn,
    OperationPatchIn,
    SchemaFieldIn,
)
from .seed import blank, kind_of, major_of, open_connection, tool_title
from .tool_users import ToolUsers
from .workflows import StaticWorkflows, WorkflowDirectory

Traffic = dict[tuple[str, str | None], CallStats]
NO_TRAFFIC = CallStats(calls=0, errors=0, p95_ms=0)
NO_CALLS = DayStats(count=0, errors=0, p95_ms=0)


class Rates(TypedDict):
    calls24h: int
    errorRate: float
    p95Ms: int


def _rates(t: CallStats) -> Rates:
    return {"calls24h": t.calls, "errorRate": t.errors / t.calls if t.calls else 0, "p95Ms": t.p95_ms}


class Skip(TypedDict):
    id: str
    reason: str


class BulkOutcome(TypedDict):
    """What a bulk change did: the ids it changed and each one it left, with why."""

    updated: list[str]
    skipped: list[Skip]


class CallShape(TypedDict, total=False):
    """The call-shape fields of an operation an edit sets: a key is present only when the edit sent it."""

    method: str | None
    path: str | None
    headers: list[Header] | None
    body: str | None
    body_encoding: str | None
    response_transform: str | None
    timeout_ms: int | None


class TestDraft(TypedDict, total=False):
    """The workbench's unsaved transform and mock: a key is present only when the caller sent it, and `None` sent
    means no transform or the default mock."""

    response_transform: str | None
    stub: JsonValue


class TestRun(TypedDict):
    """One test of an operation. The optional keys are the ones the caller sent."""

    operation: str
    context_id: str
    target: Literal["stub", "sandbox"]
    input: dict[str, JsonValue]
    simulate_approval: NotRequired[bool]
    confirmed: NotRequired[bool]
    draft: NotRequired[TestDraft | None]
    secret_values: NotRequired[dict[str, str] | None]
    environment: NotRequired[str | None]


def test_run(body: ModuleTestIn) -> TestRun:
    """A test request as `ModuleService.test` reads it: only the keys the caller sent, and in a draft only the keys it
    sent, so a draft that leaves the mock out uses the operation's own."""
    run: TestRun = {
        "operation": body.operation,
        "context_id": body.context_id,
        "target": body.target,
        "input": body.input,
    }
    sent = body.model_fields_set
    if "simulate_approval" in sent:
        run["simulate_approval"] = body.simulate_approval
    if "confirmed" in sent:
        run["confirmed"] = body.confirmed
    if "secret_values" in sent:
        run["secret_values"] = body.secret_values
    if "environment" in sent:
        run["environment"] = body.environment
    if "draft" in sent:
        draft: TestDraft | None = None
        if body.draft is not None:
            draft = {}
            if "response_transform" in body.draft.model_fields_set:
                draft["response_transform"] = body.draft.response_transform
            if "stub" in body.draft.model_fields_set:
                draft["stub"] = body.draft.stub
        run["draft"] = draft
    return run


class BoundValue(TypedDict):
    arg: str
    value: JsonValue
    source: str


class InvalidInput(TypedDict):
    field: str
    message: str


class TestLog(TypedDict):
    atMs: float
    message: str


class TestResult(TypedDict, total=False):
    """A test's answer as the console reads it. A refused one carries the reason; an allowed one the answer, and a
    sandbox run the call it made. Keys are set in the order below."""

    decision: Literal["allow", "deny", "invalid"]
    denyReason: str
    denyMessage: str
    status: int
    latencyMs: int
    bound: list[BoundValue]
    wouldPause: bool
    invalid: list[InvalidInput]
    output: JsonValue
    masked: list[str]
    callId: str
    testApprovalToken: str
    mockId: str
    reachedHost: str | None
    stubbed: bool
    rawResponse: JsonValue
    transformError: str
    request: Json
    log: list[TestLog]


class WorkflowRef(TypedDict):
    id: str
    name: str


class PendingReview(TypedDict):
    id: str | None
    version: str
    requestedBy: str
    requestedAt: str | None


class ModuleRow(TypedDict):
    """A module as the list shows it (and the detail begins). `nextExpiry`, `connectionId`, `unsetSecrets` and
    `canEdit` are set only when the module has one, the list asks for secrets, or the caller is a list's reader."""

    id: str
    name: str
    displayName: str
    system: str
    description: str
    type: str
    status: str
    version: str
    major: int
    ownerTeam: str
    endpoint: str | None
    operationCount: int
    accessClasses: list[str]
    approvalState: str
    pendingApprovals: int
    workflows: list[WorkflowRef]
    calls24h: int
    errorRate: float
    p95Ms: int
    reachable: bool
    drift: bool
    connection: ConnectionView | None
    signIn: str
    updatedAt: str | None
    nextExpiry: NotRequired[str | None]
    # Set after the fields above, in this order.
    pendingReview: NotRequired[PendingReview | None]
    connectionId: NotRequired[str]
    templateId: NotRequired[str | None]
    protection: NotRequired[str | None]
    unsetSecrets: NotRequired[int]
    canEdit: NotRequired[bool]


class RunContext(TypedDict):
    """Who a test run acts as: the module owner, who needs no workflow approval, and the values bound fields take."""

    id: str
    label: str
    workflowId: str
    workflowName: str
    caseId: str
    bindings: dict[str, JsonValue]


class ApprovalCore(TypedDict):
    id: str
    workflowId: str
    workflowName: str
    environment: str
    major: int
    operations: list[str]
    requestedBy: str
    justification: str
    status: str


class ApprovalView(ApprovalCore, total=False):
    """A workflow's approval as the API shows it; a field with no value is left out, so a key present is not null."""

    constraints: str | None
    requestedAt: str | None
    decidedBy: str | None
    decidedAt: str | None
    expiresAt: str | None
    reason: str | None
    reviewId: str | None
    deciderTeam: str | None


class ModuleListStats(TypedDict):
    """The totals over every module the team sees, as the list's header shows them."""

    modules: int
    operations: int
    calls24h: int
    errorRate: float
    expiringApprovals: int
    expiringModules: int


class ModuleListTotals(TypedDict):
    stats: ModuleListStats
    viewCounts: dict[str, int]


class ModulePage(ListPage[ModuleRow], ModuleListTotals):
    """A page of modules with the totals and each view's count beside it."""


class GrantRow(ApprovalView):
    """One row of the grants page: the approval and the module it is on."""

    moduleId: str
    moduleName: str


class VersionView(TypedDict, total=False):
    """A published version as the API shows it; a field with no value is left out."""

    version: str
    major: int
    status: str
    publishedAt: str | None
    publishedBy: str
    note: str
    changes: list[Change]
    pinnedBy: list[PinnedBy]
    reachability: list[Reachability]
    reviewId: str | None
    requestedAt: str | None
    reviewer: str | None
    finding: str | None
    reviewRequired: bool | None
    policy: str | None


class Rights(TypedDict):
    canEdit: bool
    canDelete: bool
    canPublish: bool


class ModuleDetail(ModuleRow):
    """A module's page: its row, settings, operations, approvals and versions, and what the caller may do with it."""

    ownerContacts: list[str]
    auth: Json
    timeoutMs: int
    egressHosts: list[str]
    dataClassification: str
    operations: list[OperationView]
    pendingChanges: list[Change]
    approvals: list[ApprovalView]
    versions: list[VersionView]
    runContexts: list[RunContext]
    canDelete: NotRequired[bool]
    canPublish: NotRequired[bool]


class SecretSetting(TypedDict):
    name: str
    set: bool
    available: bool


class AnswerView(TypedDict, total=False):
    answer: str
    answerSource: str
    answerRole: str | None
    waits: bool


class OperationView(AnswerView):
    """An operation as the tool page shows it; a write also carries its approval answer for the team in view."""

    id: str
    toolId: str
    name: str
    description: str
    access: str
    enabled: bool
    input: list[InputField]
    maskedOutput: list[str]
    binding: Binding | None
    rateLimitPerMin: int
    requiresApproval: bool | None
    approvalMode: str | None
    reviewerRole: str | None
    approvers: int
    approverTeam: str | None
    stepUp: bool
    idempotent: bool
    needsPerson: bool
    scopes: list[str]
    calls24h: int
    errorRate: float
    p95Ms: int
    approvedWorkflows: int
    method: NotRequired[str]
    path: NotRequired[str]
    executor: NotRequired[str]
    code: NotRequired[CodeSettings]
    headers: NotRequired[list[Header]]
    signInHeader: NotRequired[str | None]
    body: NotRequired[str]
    bodyEncoding: NotRequired[str]
    responseTransform: NotRequired[str]
    timeoutMs: NotRequired[int]
    amountMax: NotRequired[float]
    secrets: NotRequired[list[SecretSetting]]
    stub: NotRequired[JsonValue]


# Short enough that an approval granted for 30 days (the test default) is not expiring the day it is granted.
EXPIRING = timedelta(days=7)
GRANT_VIEWS = ("active", "expiring", "requested", "expired", "ended", "all")
MODULE_VIEWS = ("all", "needs_approval", "expiring", "expired", "failing", "security_review")
FAILING_RATE = 0.02
ACCESS_ORDER = ("read", "write")
WRITES = {"write"}
# The case id of a run context with no case: the builder types the bound values.
# The run context of the module's own team trying it, with no workflow and no case.
OWNER_CONTEXT = "owner"
SAMPLE_CASE = "sample"
STATUS_ORDER = {"requested": 0, "approved": 1, "expired": 2, "rejected": 3, "revoked": 4}
CREDENTIAL_HEADER = re.compile(r"^(authorization|x-api-key|cookie)$", re.IGNORECASE)
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


# A team's write approval levels as `WriteApprovals.levels` answers them: (team level, per-app levels).
Levels = tuple[Json | None, Json]


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
    """Who is asking and in which team, from ops_identity's principal; what they may do is `can` on `principal`.
    `verified` is False only for the dev-header principal, which carries no roles, so role rules apply to anyone with
    a token."""

    tenant_id: str
    name: str
    team: Team
    verified: bool = False
    # The verified principal, which `ops_access.can` decides on; None for a caller made in code (the seed).
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
    code: str = "role_required",
    protection: str | None = None,
    requested_by: tuple[str | None, ...] = (),
) -> None:
    """`ops_access.can` for a tools-service caller: the grid decides, in the team the request acts in, or in the
    Security team for the actions held there. A caller with no principal (the seed) acts as the system. `requested_by`
    is refused only while the tenant's requesterMayDecide policy is off."""
    if who.principal is None:
        return
    Access().can(who.principal, area, action, what=what, code=code, protection=protection, requested_by=requested_by)


def decides_security_reviews(who: Caller) -> bool:
    """Whether the caller acts in the workspace's Security team and may decide its reviews there: they read every
    team's module waiting on its security review, and change none of it (writes still need the module's team)."""
    p = who.principal
    if p is None:
        return False
    access = Access()
    security = access.security_team_of(p)
    return (
        security is not None
        and who.team.id == security
        and access.may(p, "reviews", "decide", team=security, from_any_team=True, what="security reviews")
    )


def link_calls_of(who: Caller) -> str | None:
    """mcp.view, for a link's calls: None reads everyone's, a subject reads only the calls that caller made."""
    if who.principal is None:
        return None
    scope = Access().can(who.principal, "mcp", "view", what="the link's calls")
    return who.principal.sub if scope == "own" else None


def reads_teamless_calls(who: Caller) -> bool:
    """Whether the caller reads the calls logged with no team (a tool call that named none, refused): activity.view
    held in every team (`*`), as the account's own audit entries are read in platform-service. A team's own reader,
    a service token and an API key read their team's calls only."""
    p = who.principal
    return p is not None and Access().may(
        p, "activity", "view", team=ANY_TEAM, from_any_team=True, what="the calls that named no team"
    )


def _not_a_plugin(m: Aggregate) -> None:
    """A plugin's module changes only with its installed package: no route edits, publishes, deletes or asks
    access for it, whoever asks, admins included."""
    if str(m.get("template_id") or "").startswith("plugin:"):
        raise Forbidden(
            f"{m['display_name']} is a plugin's tools; they change only when the plugin is upgraded.",
            code="plugin_module",
        )


class _Provisioned(TypedDict, total=False):
    template_id: str | None
    protection: str | None


def _provisioned(who: Caller, i: ModuleIn | BlankModuleIn | ModuleDetailsPatchIn) -> _Provisioned:
    """The template fields a create or patch carries, refused with `provisioner_only` unless the caller is a
    service token holding `tools:provision`: a person setting them could take a template's slot or lock others out."""
    fields: _Provisioned = {}
    if i.template_id is not None:
        fields["template_id"] = i.template_id
    if i.protection is not None:
        fields["protection"] = i.protection
    if fields and who.principal is not None:
        require_provisioner(who.principal, "tools")
    return fields


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _provision(m: Module, fields: _Provisioned) -> None:
    if "template_id" in fields:
        m["template_id"] = fields["template_id"]
    if "protection" in fields:
        m["protection"] = fields["protection"]


def _code_settings(c: CodeSettingsIn) -> CodeSettings:
    """A code operation's settings as stored and sent to runner-service."""
    return {
        "source": c.source,
        "entry": c.entry or "main",
        "bindings": list(dict.fromkeys(c.bindings or [])),
        "secrets": list(dict.fromkeys(c.secrets or [])),
        "limits": {"memoryMb": c.limits.memory_mb, "timeS": c.limits.time_s, "calls": c.limits.calls},
    }


def _kind_of(i: ModuleIn) -> str:
    """A new module's kind: as given, else what its first operations are (the kind follows the executor)."""
    if i.type:
        return str(i.type)
    if i.function:
        return "code"
    return str(i.source.kind) if i.source else "http"


def _input_field(f: SchemaFieldIn) -> InputField:
    """A field as a request sends it: every key, an unset one as null."""
    return {
        "name": f.name,
        "type": f.type,
        "required": f.required,
        "description": f.description,
        "format": f.format,
        "enum": f.enum,
        "example": f.example,
        "default": f.default,
    }


def _picked(o: DiscoveredOperationIn) -> DiscoveredOperation:
    """An operation a caller listed in full, as a source describes one."""
    return {
        "name": o.name,
        "description": o.description,
        "access": o.access,
        "method": o.method,
        "path": o.path,
        "group": o.group,
        "input": [_input_field(f) for f in o.input],
        "headers": [],
    }


def _code_operation(f: CodeOperationIn) -> DiscoveredOperation:
    """A new code operation."""
    return {
        "name": f.name,
        "description": f.description,
        "access": f.access,
        "method": None,
        "path": None,
        "group": "functions",
        "input": [_input_field(x) for x in f.input],
        "headers": [],
        "executor": "code",
        "code": _code_settings(f.code),
    }


def _kebab(s: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))


def _not_allowed(host: str) -> Unprocessable:
    return Unprocessable(
        f"{host} is not on the egress allow-list. An admin adds it under Egress before a module can call it.",
        code="egress_host_not_allowed",
    )


def _sample_field(name: str) -> InputField:
    return {"name": name, "type": "string", "required": True}


def _workflow_names(mods: Sequence[ModuleGrants]) -> dict[str, str]:
    """Each workflow's name as its approvals recorded it from agents-service, for the call log."""
    return {a["workflow_id"]: a["workflow_name"] for m in mods for a in m["approvals"]}


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _reviewed(op: Operation | StoredOperation, key: str) -> Any:
    """The part of a reviewed field Security reviews. For the input that is each field's name, type, whether it is
    required, its allowed values and its default (a default is sent for the agent on reads, so it changes what a call
    does); a description or example changes nothing a call sends."""
    if key != "input":
        return _plain(op.get(key))
    return sorted(
        (f["name"], f["type"], bool(f.get("required")), list(f.get("enum") or []), json.dumps(f.get("default")))
        for f in op.get("input") or []
    )


_MODE_WORDS: dict[str | None, str] = {
    None: "follows the app",
    "none": "runs without asking",
    "person": "asks the person",
    "reviewer": "asks a reviewer",
}


def _differs_from_published(m: Aggregate) -> bool:
    """Whether the operations about to go live differ from the published ones (the baseline) in anything Security
    reviews. Publish decides major from this, never from the edit history alone, so a change reaches calls without
    review by no route: an edit, an import, or a declined version's edits left in place."""
    baseline = m["baseline"]
    if baseline is None:
        return False
    published = {o.get("id"): o for o in published_operations(baseline)}
    for o in m["operations"]:
        before = published.get(o["id"])
        if before is None:
            return True
        if any(_reviewed(o, k) != _reviewed(before, k) for k in REVIEWED if k in before):
            return True
    return False


def _refuse_during_review(m: Aggregate, what: str) -> None:
    """While a version waits for Security, what it approves must be exactly what calls switch to: an edit, a discard
    or another version on top would ride along unreviewed or leave the approval deciding nothing."""
    if any(v["status"] == "in_review" for v in m["versions"]):
        raise Conflict(f"A version is waiting for Security's review; {what} once it is decided.")


def refuse(problems: list[str]) -> None:
    """One 400 for every problem a save found: the message reads them all, and `details.problems` lists them
    for a form to show each beside its field."""
    if len(problems) == 1:
        raise ValidationFailed(problems[0], details={"problems": problems})
    if problems:
        raise ValidationFailed(f"{len(problems)} problems: " + " ".join(problems), details={"problems": problems})


def sign_in_fits(module_sign_in: str, conn: Account) -> None:
    """A module takes only a connection whose sign-in it supports: `team` a team connection, `person` one each
    person signs in to (the team backup included), `person_or_team` any; refused when the connection is chosen."""
    module_sign_in = sign_in_of(module_sign_in)
    given = str(conn.sign_in or "team")
    if module_sign_in == "person_or_team" or (module_sign_in == "team") == (given == "team"):
        return
    want = "the team's account" if module_sign_in == "team" else "each person's own account"
    raise ValidationFailed(
        f"This module signs in with {want}, and {conn.name} does not. Pick another connection.",
        code="sign_in_mismatch",
    )


class ModuleService:
    # A plugin tool's display name, set once the plugin host is up (`PluginHost.title_of`); other modules have none.
    titles: TitleOf | None = None
    # agents-service's agents and workflows that use each tool, which name the call log's agent and workflow ids.
    users: ToolUsers | None = None
    # The team's connection for a plugin's module (`PluginHost.team_connection`), set once the plugin host is up.
    team_connections: Callable[[str, str, Aggregate], Awaitable[str | None]] | None = None
    # Whether a plugin tool's address waits for its account's sign-in (`PluginHost.awaits_sign_in`), set once the
    # plugin host is up: the account then holds the sign-in host, which is not the tool's address.
    awaits_sign_in: Callable[[Aggregate, Account], bool] | None = None
    # The installed plugins' ids, whose team bindings sign a plugin's module in for the list's reachable column.
    installed_plugins: Callable[[], list[str]] | None = None
    # A tool page's Real run (`GatewayCalls.console_run`), set by create_gateway_app: Real goes through the gateway's
    # checks, never a path of its own.
    real_runs: Callable[..., Awaitable[ConsoleRan | ConsoleRefused]] | None = None
    # The gateway's own reader of the team's approval settings, set by create_gateway_app: a test run waits exactly
    # when the same call from chat would. Left as is, the settings cannot be read and every write without its own
    # answer waits.
    approvals: WriteApprovals = WriteApprovals()

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
        # agents-service's Reviews, where a version's review opens; without it no review can open.
        self.reviews = reviews
        # The team's publish-review mode, read live from platform-service on each publish. Without a
        # reader (no platform URL, the tests) a publish follows the default "major": a major version waits.
        self.publish_policy = publish_policy
        # requesterMayDecide for access decisions applied for a workflow; without it the asker never decides.
        self.requester_policy = requester_policy
        # The tenant's connections, in this service's own database.
        self.connections = ConnectionStore(store.engine)
        # The Tools list, chosen and paged in SQL.
        self.listing = ModuleList(store.engine)
        # The operations' mock answers, which Try it's test answer reads as a test run does.
        self.mocks = MockAnswers(MockStore(store.engine))
        # Signs the test console's real reads in through the module's connection, in the test environment; without it
        # a connection adds nothing to them.
        self.auth = auth

    # ── Derived views ─────────────────────────────────────────────────────

    def _approval_status(self, a: Approval) -> str:
        expired = a["status"] == "approved" and a["expires_at"] is not None and a["expires_at"] < self.clock()
        return "expired" if expired else a["status"]

    def _approvals(self, m: Aggregate) -> list[Approval]:
        return [self._with_status(a) for a in m["approvals"]]

    @staticmethod
    def _deprecated(v: Version) -> Version:
        return {**v, "status": "deprecated"}

    def _with_status(self, a: Approval) -> Approval:
        return {**a, "status": self._approval_status(a)}

    def _owners(self, m: Aggregate) -> list[str | None]:
        """The module's owner group and those of the teams owning the workflows it is approved for, as each approval
        recorded them when it was requested (the workflow's team comes from agents-service)."""
        return self.dir.owners(m)

    def _since(self, delta: timedelta) -> str:
        """`delta` before now, in the call log's created_at format, so the two compare as text."""
        return (self.clock() - delta).astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    async def _traffic(self, tenant_id: str, teams: list[str], mods: list[Aggregate]) -> Traffic:
        """The last day's calls on `mods` made in `teams`: a shared module's counts are the team's own calls."""
        since = self._since(timedelta(days=1))
        return await self.calls.traffic([m["id"] for m in mods], since, tenant_id=tenant_id, team_ids=teams)

    def _call_teams(self, who: Caller) -> list[str]:
        """The teams whose calls the caller reads: its own acting team. A call is its team's even on a module
        every team shares, so Usage never shows another team's calls. Only the dev header caller acting in an all-scope
        team reads every directory team's, as `_sees` lets it read every team's modules."""
        if not who.verified and who.team.scope == "all":
            return [t.id for t in self.dir.teams]
        return [who.team.id]

    async def _secret_names(self, tenant_id: str, mods: list[Aggregate]) -> dict[str | None, set[str]]:
        """The names of the secrets each of the modules' teams has set (a module reads its own team's only);
        values are never read here."""
        if self.secrets is None:
            return {}
        owners = sorted({str(m["team_id"]) for m in mods if m["team_id"]})
        return {team: {r.name for r in await self.secrets.store.listed(tenant_id, team)} for team in owners}

    async def _as_team_sees(self, tenant_id: str, team_id: str, mods: list[Aggregate]) -> list[Aggregate]:
        """The modules with a plugin's module showing the team's own connection: the gateway signs a plugin
        tool in through the team's binding, so its page names that account instead of no connection."""
        if self.team_connections is None:
            return mods
        out: list[Aggregate] = []
        for m in mods:
            if not m["connection_id"] and str(m.get("template_id") or "").startswith("plugin:"):
                conn = await self.team_connections(tenant_id, team_id, m)
                out.append(cast(Aggregate, {**m, "connection_id": conn}))
            else:
                out.append(m)
        return out

    async def _connections_of(self, tenant_id: str, mods: list[Aggregate]) -> dict[str, Account]:
        return await self.connections.by_ids(
            tenant_id, sorted({str(m["connection_id"]) for m in mods if m["connection_id"]})
        )

    def _row(
        self,
        m: Aggregate,
        traffic: Traffic,
        have: dict[str | None, set[str]] | None = None,
        conns: dict[str, Account] | None = None,
    ) -> ModuleRow:
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
        workflows: dict[str, WorkflowRef] = {
            a["workflow_id"]: {"id": a["workflow_id"], "name": a["workflow_name"]} for a in active
        }
        status = status_of(conn, now) if conn else ""
        waiting = conn is not None and self.awaits_sign_in is not None and self.awaits_sign_in(m, conn)
        row: ModuleRow = {
            "id": m["id"],
            "name": m["name"],
            "displayName": m["display_name"],
            "system": m["system"],
            "description": m["description"],
            "type": kind_of(m),
            "status": m["status"],
            "version": m["version"],
            "major": major_of(m["version"]),
            "ownerTeam": m["owner_team"],
            "endpoint": None if waiting else connection_base(conn) if conn else "",
            "operationCount": len(ops),
            "accessClasses": [acc for acc in ACCESS_ORDER if any(o["access"] == acc for o in ops)],
            "approvalState": state,
            "pendingApprovals": pending,
            "workflows": list(workflows.values()),
            **_rates(t),
            # A connection that is revoked, expired or failing makes the system unreachable from the gateway.
            "reachable": m["reachable"] and status not in ("revoked", "needs_reconnect", "error"),
            "drift": m["drift"],
            "connection": ({**ref_of(conn, now), "baseUrl": None} if waiting else ref_of(conn, now)) if conn else None,
            "signIn": sign_in_of(m.get("sign_in")),
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

    def _run_contexts(self) -> list[RunContext]:
        """The module owner only, who needs no workflow approval. The test panel's Run as lists it alone: a
        workflow's context ran with typed sample values rather than a case, so it proved nothing a real run would."""
        return [
            {
                "id": OWNER_CONTEXT,
                "label": "Owner, no case",
                "workflowId": "",
                "workflowName": "",
                "caseId": SAMPLE_CASE,
                "bindings": {},
            }
        ]

    def _operation(
        self,
        m: Aggregate,
        o: Operation,
        approvals: list[Approval],
        t: CallStats,
        have: dict[str | None, set[str]] | None = None,
    ) -> OperationView:
        policy = approval_policy(m, o)
        out: OperationView = {
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
            "approvalMode": o.get("approval_mode"),
            "reviewerRole": o.get("reviewer_role"),
            "approvers": policy["approvers"],
            "approverTeam": policy["approver_team"],
            "stepUp": policy["step_up"],
            "idempotent": o["access"] != "read",
            "needsPerson": bool(o.get("needs_person")),
            "scopes": list(o.get("scopes") or []),
            **_rates(t),
            "approvedWorkflows": len(
                {a["workflow_id"] for a in approvals if a["status"] == "approved" and o["name"] in a["operations"]}
            ),
        }
        for key, col in (("method", "method"), ("path", "path")):
            if o[col] is not None:
                out[key] = o[col]
        out["executor"] = o["executor"]
        code = o.get("code")
        if code:
            out["code"] = code
        out["headers"] = o.get("headers") or []
        # A tool saved before sign-in headers were refused still sends one; its page asks to move it to the app.
        held = o.get("headers") or []
        out["signInHeader"] = next(
            (h["key"] for h in held if CREDENTIAL_HEADER.match(h["key"].strip()) and h["value"].strip()), None
        )
        for key, col in (
            ("body", "body"),
            ("bodyEncoding", "body_encoding"),
            ("responseTransform", "response_transform"),
            ("timeoutMs", "timeout_ms"),
        ):
            if o.get(col) is not None:
                out[key] = o[col]
        if o["amount_max"] is not None:
            out["amountMax"] = float(o["amount_max"])
        if have is not None:
            # Set in the module's own team, the only secrets the gateway reads for it; `available` says the same, for
            # callers written when a secret could be limited to some teams.
            mine = have.get(m["team_id"], set())
            out["secrets"] = [{"name": n, "set": n in mine, "available": n in mine} for n in secret_names(o)]
        # The operation's example mock under its old name, while the console still reads it; removed in D3c/D3d,
        # when the console reads GET .../mocks?environment=example.
        out["stub"] = o.get("stub")
        return out

    def _rights(self, who: Caller, m: Aggregate) -> Rights:
        """What the caller may do with this module, by the check each write route runs: `can` for the action
        with the module's protection, so the console's buttons and the routes never disagree."""
        return {
            "canEdit": self._may(who, m, "edit"),
            "canDelete": self._may(who, m, "delete"),
            "canPublish": self._may(who, m, "publish"),
        }

    def _may(self, who: Caller, m: Aggregate, action: str) -> bool:
        """One of `_rights`' flags: the module is the caller's team's and `can` allows the action on it. Reads only
        the module, so a list's page sets it on each row without a statement."""
        if not self._team_owns(who, m):
            return False
        try:
            _can(who, "tools", action, what="it", protection=m.get("protection"))
        except Forbidden:
            return False
        return True

    async def _levels(self, tenant_id: str, team: Team) -> Levels:
        """The team's write approval levels from platform-service. A route on the request transaction reads them before
        its first store call, so no connection is held while platform-service answers."""
        return await self.approvals.levels(tenant_id, team.id)

    async def _detail(
        self, m: Aggregate, team: Team, who: Caller | None = None, *, levels: Levels | None = None
    ) -> ModuleDetail:
        """`who` is the person asking; their rights on the module ride along. A service applying a decision has none.
        Without `levels` they are asked of platform-service here, after the module's reads."""
        m = (await self._as_team_sees(str(m["tenant_id"]), team.id, [m]))[0]
        traffic = await self._traffic(str(m["tenant_id"]), self._call_teams(who) if who else [team.id], [m])
        have = await self._secret_names(str(m["tenant_id"]), [m])
        approvals = self._approvals(m)
        ordered = sorted(
            approvals,
            key=lambda a: (STATUS_ORDER[a["status"]], _iso(a["expires_at"]) or "9"),
        )
        auth = auth_of(m["auth"])
        detail: ModuleDetail = {
            **self._row(m, traffic, have, await self._connections_of(str(m["tenant_id"]), [m])),
            "ownerContacts": m["owner_contacts"],
            "auth": auth,
            "timeoutMs": m["timeout_ms"],
            "egressHosts": m["egress_hosts"],
            "dataClassification": m["data_classification"],
            "operations": await self._with_answers(
                m,
                team,
                [
                    self._operation(m, o, approvals, traffic.get((m["id"], o["name"]), NO_TRAFFIC), have)
                    for o in m["operations"]
                ],
                levels,
            ),
            "pendingChanges": m["pending"],
            "approvals": [self._approval_out(a) for a in ordered],
            "versions": [self._version_out(v) for v in reversed(m["versions"])],
            "runContexts": self._run_contexts(),
        }
        if who is not None:
            rights = self._rights(who, m)
            detail["canEdit"], detail["canDelete"], detail["canPublish"] = (
                rights["canEdit"],
                rights["canDelete"],
                rights["canPublish"],
            )
        return detail

    async def _with_answers(
        self, m: Aggregate, team: Team, shown: list[OperationView], levels: Levels | None = None
    ) -> list[OperationView]:
        """Each write's answer for the team in view (waits, who answers, which level), from the resolver the gateway
        runs, so the tool page and the operations table never apply the rule themselves."""
        tenant = str(m["tenant_id"])
        levels = levels or await self.approvals.levels(tenant, team.id)
        by_name = {str(o["name"]): o for o in m["operations"]}
        out: list[OperationView] = []
        for row in shown:
            o = by_name[str(row["name"])]
            if o["access"] not in WRITES:
                out.append(row)
                continue
            ans = await self.approvals.answer(
                tenant,
                team.id,
                m,
                access=o["access"],
                setting=tool_mode(o),
                reviewer_role=o.get("reviewer_role"),
                approvers=approval_policy(m, o)["approvers"],
                levels=levels,
                test_account=bool(m.get("sandbox")),
                tool=str(o["name"]),
            )
            out.append(
                {
                    **row,
                    "answer": ans["answer"],
                    "answerSource": ans["source"],
                    "answerRole": ans["reviewerRole"],
                    "waits": ans["waits"],
                }
            )
        return out

    @staticmethod
    def _drop_none[V: Mapping[str, object]](d: V) -> V:
        return cast(V, {k: v for k, v in d.items() if v is not None})

    def _approval_out(self, a: Approval) -> ApprovalView:
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
                # The Human Tasks review deciding it and the team whose reviewers do.
                "reviewId": a.get("review_id"),
                "deciderTeam": a.get("decider_team"),
            }
        )

    def _version_out(self, v: Version) -> VersionView:
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

    def _sees(self, who: Caller, m: ModuleGrants) -> bool:
        """The caller's team reads the module: its own, a workspace-level one, or one approved for its workflows. Only
        the dev header caller acting in one of the dev seed's all-scope teams reads every team's."""
        return self.dir.sees_module(who.team, m) or (not who.verified and who.team.scope == "all")

    async def _owned(self, who: Caller, module_id: str) -> Aggregate:
        """The module, when the caller's team owns it (or it is workspace-level); 404 otherwise, as for one it cannot
        see. A team that reads a module through its workflow's grant uses it and changes nothing of it."""
        m = await self._find(who, module_id)
        if not self._team_owns(who, m):
            raise NotFound("Module")
        return m

    @staticmethod
    def _team_owns(who: Caller, m: Aggregate) -> bool:
        """The one team check every module write, test and run shares, and the detail's can* flags with them."""
        return owns_module(who.team, m.get("team_id"), verified=who.verified)

    async def _changeable(self, who: Caller, module_id: str, action: str = "edit") -> Aggregate:
        """The module, when the caller may change it: its team's, and a `system` module is the provisioner's alone."""
        m = await self._owned(who, module_id)
        _not_a_plugin(m)
        _can(
            who,
            "tools",
            action,
            what=f"{m['display_name']}",
            protection=m.get("protection"),
        )
        return m

    async def _save(self, m: Aggregate, *, touch: bool = True, events: Sequence[ServiceEvent] = ()) -> Aggregate:
        """`events` are service events written in the same transaction."""
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

    async def grants(self, who: Caller, q: ListParams) -> ListPage[GrantRow]:
        """Every workflow's access to the modules the caller's team sees, newest request first, one page of the view
        `q` names (`all` when none), searched by workflow, module or requester; `facets.view` counts each view."""
        view = (q.filters.get("view") or ["all"])[-1]
        if view not in GRANT_VIEWS:
            raise ValidationFailed(f"There is no view {view!r}: ask for one of {', '.join(GRANT_VIEWS)}.")
        views = grant_views(self.clock(), EXPIRING)
        page, counts = await self.store.grants(who.tenant_id, q, view=views[view], views=views)
        granted: list[GrantRow] = [
            {
                **self._approval_out(self._with_status(APPROVAL.validate_python(r))),
                "moduleId": r["module_id"],
                "moduleName": r["module_name"],
            }
            for r in page["data"]
        ]
        return {**page, "data": granted, "facets": {"view": counts}}

    async def list(self, who: Caller, q: ListParams) -> ModulePage:
        """One page of the modules the caller's team sees, in the view `q` names (`all` when none), with each view's
        count, the facets and the totals of every module seen: chosen, counted and paged in SQL
        (store/module_list.py), then the page's modules read in full."""
        view = (q.filters.get("view") or ["all"])[-1]
        if view not in MODULE_VIEWS:
            raise ValidationFailed(f"There is no view {view!r}: ask for one of {', '.join(MODULE_VIEWS)}.")
        teams = self._call_teams(who)
        window = Window(
            now=self.clock(),
            expiring=EXPIRING,
            failing_rate=FAILING_RATE,
            since=self._since(timedelta(days=1)),
            call_teams=teams,
            plugins=self.installed_plugins() if self.installed_plugins is not None else [],
        )
        every = not who.verified and who.team.scope == "all"  # as `_sees`: the dev caller in an all-scope team
        reviews = view == "security_review" and decides_security_reviews(who)
        page, totals = await self.listing.page(
            who.tenant_id,
            who.team.id,
            q,
            view=view,
            w=window,
            seen_by=None if every else who.team.id,
            # Security's queue only: its other views stay its own team's modules.
            reviews=reviews,
        )
        # A plugin's module shows the team's own account (`_as_team_sees`), read with the page.
        signs_in = {str(r["id"]): r["connection_id"] for r in page["data"]}
        chosen = await self.store.chosen(who.tenant_id, list(signs_in), reviews=reviews)
        mods: list[Aggregate] = [{**m, "connection_id": signs_in[m["id"]]} for m in chosen]
        traffic = await self._traffic(who.tenant_id, teams, mods)
        have = await self._secret_names(who.tenant_id, mods)
        conns = await self._connections_of(who.tenant_id, mods)
        calls, errors = totals["calls"], totals["errors"]
        return {
            **page,
            # The detail's canEdit rule, so a row of another team's module offers no edit its routes would refuse.
            "data": [{**self._row(m, traffic, have, conns), "canEdit": self._may(who, m, "edit")} for m in mods],
            "stats": {
                "modules": totals["all"],
                "operations": totals["operations"],
                "calls24h": calls,
                "errorRate": errors / calls if calls else 0,
                "expiringApprovals": totals["expiring_approvals"],
                "expiringModules": totals["expiring"],
            },
            "viewCounts": {v: totals[v] for v in MODULE_VIEWS},
        }

    async def get(self, who: Caller, module_id: str) -> ModuleDetail:
        levels = await self._levels(who.tenant_id, who.team)
        reviews = decides_security_reviews(who)
        found = await self.store.get(who.tenant_id, module_id, reviews=reviews) if reviews else None
        # A module waiting on Security's review opens for its reviewer, read only; every other read is the team's.
        m = found if found is not None and not self._sees(who, found) else await self._find(who, module_id)
        return await self._detail(m, who.team, who, levels=levels)

    async def activity(self, who: Caller, module_id: str) -> ModuleActivityJson:
        """Calls per UTC day over the last 14 days from the call log, days without calls at zero, and the latest calls
        with their callers: the call log's view of one module, so read under activity.view as the log is."""
        _can(who, "activity", "view", what="the tool-call log")
        m = await self._find(who, module_id)
        today = self.clock().astimezone(UTC).date()
        first = today - timedelta(days=13)
        logged = await self.calls.daily(
            m["id"], first.isoformat(), tenant_id=who.tenant_id, team_ids=self._call_teams(who)
        )
        days = [
            DayJson(date=d, **logged.get(d, NO_CALLS).model_dump(by_alias=True))
            for d in ((first + timedelta(days=i)).isoformat() for i in range(14))
        ]
        since = self._since(timedelta(days=1))
        tenant, teams = who.tenant_id, self._call_teams(who)
        _, denied = await self.calls.search(
            tenant_id=tenant, team_ids=teams, module_ids=[m["id"]], decision="deny", since=since, limit=1
        )
        recent, _ = await self.calls.search(tenant_id=tenant, team_ids=teams, module_ids=[m["id"]], limit=12)
        return {
            "days": days,
            "denied24h": denied,
            "recent": [call_row(r, _workflow_names([m]), m, self._title(m, r.tool)) for r in recent],
        }

    def _title(self, module: ModuleColumns | None, tool: str) -> str | None:
        return tool_title(module, tool, self.titles) if module is not None else None

    async def executions(
        self,
        who: Caller,
        params: ListParams,
        *,
        counted: bool = True,
        tool: str | None = None,
        module_ids: list[str] | None = None,
        thread_id: str | None = None,
        decision: str | None = None,
        key: str | None = None,
        call_id: str | None = None,
        link_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> ListPage[CallRowJson]:
        """Every call made in the caller's team, newest first, on the modules that team sees. `key` finds the calls
        sent under one idempotency key: how a workflow run reconciles a write after a crash. `call_id` lists that one
        call, so a chat's Open call link shows the call it was made from. The log names who called what, so it is read
        under activity.view. A link's calls are read under mcp.view instead, so a member with `own` sees only the calls
        they made through it."""
        mine = link_calls_of(who) if link_id is not None else None
        if link_id is None:
            _can(who, "activity", "view", what="the tool-call log")
        # One transaction for the reads; the agents and workflows are named by agents-service after it ends.
        async with isolation.request_transaction():
            mods = {m["id"]: m for m in await self.store.seen(who.tenant_id) if self._sees(who, m)}
            scope = None if not who.verified and who.team.scope == "all" else list(mods)
            if module_ids is not None:
                scope = [m for m in module_ids if scope is None or m in scope]
            if link_id is not None:
                # A link's calls are the team's own already, and a workflow started through one has no module.
                scope = None
            if key is not None:
                # A lookup by key shows a claim as it stands: one still running past its expiry reads as lost.
                await self.calls.expire_running(tenant_id=who.tenant_id, key=key)
            page = await self.calls.listed(
                params,
                counted=counted,
                tenant_id=who.tenant_id,
                team_ids=self._call_teams(who),
                # The link's calls are its team's; the other reads add the calls that named no team for an
                # every-team reader.
                teamless=link_id is None and reads_teamless_calls(who),
                tools=[tool] if tool else None,
                module_ids=scope,
                # A refused call on a tool no module holds is the team's audit evidence too; a moduleId filter asks
                # for those modules' calls only.
                moduleless=module_ids is None,
                thread_id=thread_id,
                decision=decision,
                key=key,
                call_id=call_id,
                link_id=link_id,
                sub=mine,
                since=since,
                until=until,
            )
            rows = [GatewayCall.model_validate(r) for r in page["data"]]
            # Only the modules the page's rows name are read, as rows.
            shown = await self.store.headers(
                who.tenant_id, sorted({r.module_id for r in rows if r.module_id is not None and r.module_id in mods})
            )
        names = _workflow_names(list(mods.values()))
        listed = [
            call_row(r, names, shown.get(r.module_id or ""), self._title(shown.get(r.module_id or ""), r.tool))
            for r in rows
        ]
        return {**page, "data": await self._named(who, listed)}

    async def _named(self, who: Caller, rows: list[CallRowJson]) -> list[CallRowJson]:
        """The rows with each agent and workflow named as agents-service names them, read once for the tools on the
        page. Unanswered, the rows keep the ids they hold: the log still lists every call."""
        if self.users is None or not rows:
            return rows
        try:
            uses = await self.users.of(who.tenant_id, who.team.id, sorted({str(r["target"]) for r in rows}))
        except ServiceUnavailable:
            return rows
        named = {(u["kind"], u["id"]): u["name"] for found in uses.values() for u in found if u.get("name")}
        for r in rows:
            if r.get("agentSlug"):
                r["agentName"] = named.get(("agent", r["agentSlug"]), r["agentName"])
            if r.get("workflowId"):
                r["workflowName"] = named.get(("workflow", r["workflowId"]), r["workflowName"])
        return rows

    async def execution(self, who: Caller, call_id: str) -> CallRowJson:
        """One call from the gateway's log, so an Activity row opens to its call. The same scope as the list: another
        team's call, or one on a module the caller's team does not see, is not found, never a different answer."""
        _can(who, "activity", "view", what="the tool-call log")
        async with isolation.request_transaction():
            row = await self.calls.get(
                call_id, tenant_id=who.tenant_id, team_ids=self._call_teams(who), teamless=reads_teamless_calls(who)
            )
            if row is None:
                raise NotFound("Call")
            mods = {m["id"]: m for m in await self.store.seen(who.tenant_id) if self._sees(who, m)}
            if (who.verified or who.team.scope != "all") and row.module_id is not None and row.module_id not in mods:
                raise NotFound("Call")
            module = (
                await self.store.headers(
                    who.tenant_id, [row.module_id] if row.module_id is not None and row.module_id in mods else []
                )
            ).get(row.module_id or "")
        return call_row(row, _workflow_names(list(mods.values())), module, self._title(module, row.tool))

    # ── Creating modules ──────────────────────────────────────────────────

    @staticmethod
    def _checked_headers(headers: Sequence[Header], problems: list[str]) -> list[Header]:
        """A sign-in header is refused whatever it holds, a {{NAME}} reference too: every custom module is on a
        connection, which signs every call in, so the key has one home. Used by add and edit alike; each
        refusal joins `problems`."""
        for header in headers:
            key, value = header["key"].strip(), header["value"].strip()
            if CREDENTIAL_HEADER.match(key) and value:
                problems.append(
                    f"The {key} header signs in, and the app's connection signs every call: set the key on the "
                    "connection, not on the tool."
                )
        return [{"key": h["key"].strip(), "value": h["value"].strip()} for h in headers if h["key"].strip()]

    @staticmethod
    def _split_url(url: str, endpoint: str) -> tuple[str, str]:
        """The base an operation's URL hangs off and its path. https only. A module with an endpoint calls every
        operation on it (the executor joins the endpoint and the path), so a URL on any other base is refused: a
        second system is a second module."""
        if url.startswith("/"):
            # A path alone hangs off the module's base address: its connection's for a custom app.
            if not endpoint:
                raise ValidationFailed("Enter the full https URL of the operation, or pick the app's connection first.")
            return endpoint.rstrip("/"), url
        parts = urlsplit(URL_VAR.sub("x", url))
        if parts.scheme != "https" or not parts.netloc:
            raise ValidationFailed("Enter the full https URL of the operation.")
        base = endpoint.rstrip("/") or f"https://{parts.netloc}"
        if url != base and not url.startswith(f"{base}/"):
            raise ValidationFailed(
                f"https://{parts.netloc} is not this module's endpoint ({base}). A second system is a second module."
            )
        return base, url[len(base) :] or "/"

    @classmethod
    def _encoding_problem(cls, body: str | None, encoding: str | None, headers: Sequence[Header]) -> str | None:
        """Why this body cannot be sent in its encoding, or None. JSON and form set Content-Type themselves, so
        a header naming another would contradict them; raw sends the text as typed, so it needs that header."""
        enc = encoding or "json"
        typed = any(h["key"].strip().lower() == "content-type" for h in headers)
        if enc == "raw":
            return None if typed or not body else "A raw body is sent as typed: add the Content-Type header it needs."
        if typed:
            name = "JSON" if enc == "json" else "Form"
            return f"Content-Type is set by the body encoding, {name}. Remove the header, or choose Raw."
        if enc == "json":
            return cls._body_problem(body)
        try:
            fields: object = json.loads(body) if body else {}
        except json.JSONDecodeError:
            fields = None
        if not isinstance(fields, dict) or not all(isinstance(v, str) for v in cast(Json, fields).values()):
            return "A form body is a set of fields, each a name and a text value such as {{email}}."
        return None

    @staticmethod
    def _body_problem(body: str | None) -> str | None:
        """Why a body template would not make JSON once its {{arg}} placeholders are filled, or None."""
        if not body or not body.strip():
            return None
        try:
            json.loads(BODY_VAR.sub("null", body))
        except json.JSONDecodeError as e:
            return f"The body is not a JSON template: {e.msg} at line {e.lineno}."
        # A placeholder is filled in as JSON (text arrives with its own quotes), so one inside a string breaks every
        # call. Filling it with "" shows which: that is still JSON where a value goes, and not inside a string.
        for name in dict.fromkeys(BODY_VAR.findall(body)):
            try:
                json.loads(BODY_VAR.sub(lambda m, n=name: '""' if m.group(1) == n else "null", body))
            except json.JSONDecodeError:
                return f"Leave {{{{{name}}}}} out of quotes in the body: it is filled in as JSON, quotes included."
        return None

    def _http_operation(self, h: HttpOperationIn, endpoint: str = "") -> tuple[DiscoveredOperation, str]:
        """One hand-built HTTP operation as a discovered one, and the base it calls. Every problem is found before
        any is reported, so one save lists them all."""
        problems: list[str] = []
        headers = self._checked_headers([{"key": x.key, "value": x.value} for x in h.headers], problems)
        if not OPERATION_NAME.match(h.name):
            problems.append("Name the operation in lower case letters, digits and underscores.")
        origin, path = "", "/"
        try:
            origin, path = self._split_url(h.url, endpoint)
        except ValidationFailed as e:
            problems.append(e.message)
        if problem := self._encoding_problem(h.body, h.body_encoding, headers):
            problems.append(problem)
        refuse(problems)
        names = [*URL_VAR.findall(h.url), *BODY_VAR.findall(h.body or "")]
        op: DiscoveredOperation = {
            "name": h.name,
            "description": h.description,
            "access": h.access,
            "method": h.method,
            "path": path,
            "group": "operations",
            "input": [_sample_field(n) for n in dict.fromkeys(names)],
            "headers": headers,
            "body": h.body,
            "body_encoding": h.body_encoding,
        }
        return op, origin

    @staticmethod
    def _added(o: Operation | DiscoveredOperation, *, major: bool) -> Change:
        return {"operation": o["name"], "kind": "added", "detail": f"New {o['access']} operation", "major": major}

    def _new_op(self, module_id: str, index: int, o: DiscoveredOperation) -> Operation:
        return {
            **operation_defaults(),
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
            "body_encoding": o.get("body_encoding"),
            "response_transform": None,
            "timeout_ms": None,
            "input": o["input"],
            "masked_output": [],
            "binding": None,
            "rate_limit_per_min": 60,
            # Not set unless someone sets it: the team default then decides, and a later change of it reaches the tool.
            "requires_approval": o.get("requires_approval"),
            "amount_max": None,
            # The source's example response when it gives one, so a stubbed call answers like the system.
            "stub": o.get("stub") if o.get("stub") is not None else {"ok": True},
            "output_shape": o.get("output_shape"),
            "response_schema": o.get("response_schema"),
            "code": o.get("code"),
        }

    async def _names_free(self, who: Caller, ops: Sequence[DiscoveredOperation]) -> None:
        taken = await self.store.names_taken(who.tenant_id, [o["name"] for o in ops], who.team.id)
        if taken:
            name = sorted(taken)[0]
            raise Conflict(f"An operation named {name} already exists in another module.")

    async def _name_free(self, who: Caller, name: str) -> bool:
        return name not in await self.store.names(who.tenant_id, who.team.id)

    async def create(self, who: Caller, i: ModuleIn) -> ModuleDetail:
        _can(who, "tools", "create", what="tools")
        template = _provisioned(who, i)
        base = _kebab(i.name)
        if not base:
            raise ValidationFailed("Name the module.")
        name = base
        if i.unique_name:
            n = 2
            while not await self._name_free(who, name):
                name, n = f"{base}-{n}", n + 1
        if not await self._name_free(who, name):
            raise Conflict(f"A module named {name} already exists.")
        if not i.display_name.strip():
            raise ValidationFailed("Give the module a display name.")
        conn = await self._usable_connection(who, i.connection_id, i.sign_in)
        ops_in: list[DiscoveredOperation] = [_picked(o) for o in i.operations or []]
        kind = _kind_of(i)
        if kind == "code":
            # A code module's functions run on runner-service: no endpoint and no egress host of its own.
            if not i.function:
                raise ValidationFailed("Write the module's first function.")
            ops_in = [_code_operation(i.function)]
        endpoint: str = i.endpoint
        if i.source and ops_in:
            # An MCP server behind sign-in lists its tools only with the connection's token.
            found = await self._discover(who, i.source, i.connection_id)
            ops_in = self._chosen(found, ops_in)
            endpoint = found["endpoint"]
        if i.http and conn is not None:
            # A custom app's base address and key live on its connection only: one beside it is refused.
            if endpoint:
                raise ValidationFailed(
                    f"The base address comes from the {conn.name} connection; leave the module's endpoint empty."
                )
            op, endpoint = self._http_operation(i.http, connection_base(conn))
            ops_in = [op]
        elif i.http:
            op, endpoint = self._http_operation(i.http)
            ops_in = [op]
        if not ops_in:
            raise ValidationFailed("Choose at least one operation to expose.")
        await self._names_free(who, ops_in)
        await self.hold_unless_listed(who, urlsplit(endpoint).hostname, conn.name if conn else i.display_name)
        if conn is None and kind != "code":
            conn = await self._open_connection(who, i.display_name, endpoint)
        elif conn is not None and endpoint:
            await self._address_on(who, conn, endpoint)
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
                input={"displayName": i.display_name, "name": name, "type": kind},
            ),
            "system": i.system.strip() or i.display_name.strip(),
            "description": f"{i.system.strip() or i.display_name.strip()} operations behind the data gateway.",
            "auth": module_auth(conn),
            "egress_hosts": [host] if host else [],
            "catalog_id": conn.catalog_id if conn else None,
            "connection_id": conn.id if conn else None,
            "sign_in": sign_in_of(i.sign_in),
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
        _provision(m, template)
        return await self._detail(await self._create(m), who.team, who)

    async def _usable_connection(self, who: Caller, connection_id: str | None, sign_in: str | None) -> Account | None:
        """The connection a new module signs in through: optional, and when one is named it must exist, be live, be
        the team's and fit the module's sign-in."""
        if connection_id is None:
            return None
        conn = await self.connections.get(who.tenant_id, connection_id)
        if conn is None:
            raise ValidationFailed("That connection no longer exists. Pick another one, or none.")
        if status_of(conn, self.clock()) == "revoked":
            raise Conflict(f"{conn.name} is revoked. Reconnect it in Connections or pick another connection.")
        if not may_use(conn, who.team.id):
            raise ValidationFailed(f"{conn.name} is not available to this team. Pick another one, or none.")
        sign_in_fits(sign_in_of(sign_in), conn)
        return conn

    async def host_passes(self, tenant_id: str, host: str) -> bool:
        """Whether `host` passes the account's egress list now (listed, or any public host under any_public)."""
        return self.egress is not None and await self.egress.host_passes(tenant_id, host)

    async def hold_unless_listed(self, who: Caller, host: str | None, app: str) -> None:
        """An app's address on a host the tenant has not listed, decided by the account's egressNewHosts policy before
        anything is saved. A host the call-time check passes (`EgressPolicy.host_passes`: any public name under
        `any_public`), a caller who may manage the egress list, or any builder under `builders`, lists it in the
        caller's name, audited: a module's hosts are rows of the list (the store's foreign key), so a host that passes
        unlisted would still be refused on save. Under `block` it is refused. Otherwise it asks the Security team:
        HostHeld with the task's run key while it waits, its reason once refused.
        Without Reviews or an egress policy the call-time check refuses the host."""
        if not host or self.egress is None or self.reviews is None:
            return
        if await self.egress.store.host_allowed(who.tenant_id, host):
            return
        passes = await self.egress.host_passes(who.tenant_id, host)
        mode = await self.egress.new_hosts.mode(who.tenant_id) if self.egress.new_hosts else "ask_security"
        manages = who.principal is not None and self._manages_egress(who)
        if passes or manages or (mode == "builders" and who.principal is not None):
            note = f"Listed when {app} first named it"
            await self.egress.store.add(who.tenant_id, "host", host, actor=who.name, note=note, at=self.clock())
            return
        if mode == "block":
            raise ValidationFailed(
                f"{host} is not an allowed address, and this account adds no new ones from here. Ask the Security "
                "team to add it on the Egress page.",
                code="egress_denied",
            )
        task = await self.reviews.open_host(
            who.credentials, tenant_id=who.tenant_id, team_id=who.team.id, host=host, app=app
        )
        if task.get("status") == "rejected":
            raise refused(host, task)
        raise HostHeld(host, str(task["id"]))

    def _manages_egress(self, who: Caller) -> bool:
        try:
            _can(who, "secrets_egress", "manage", what="the allowed hosts")
        except Forbidden:
            return False
        return True

    async def _open_connection(self, who: Caller, name: str, base: str, team_id: str | None = None) -> Account:
        """The account a custom module with none of its own keeps its address on: no sign-in, so a call reads
        it as it reads any app's. Empty until the first tool names one."""
        now = self.clock()
        row = open_connection(
            tenant_id=who.tenant_id, team_id=team_id or who.team.id, connection_id=new_id("con"), name=name, base=base,
            me=who.name, at=now,
        )  # fmt: skip
        if not await self.connections.create(row, actor=who.name, at=now):
            raise Conflict("Try again; that connection id was just taken.")
        made = await self.connections.get(who.tenant_id, str(row["id"]))
        assert made is not None
        return made

    async def _address_on(self, who: Caller, conn: Account, address: str) -> None:
        """A discovered address (an imported spec's server, an MCP server) onto the module's chosen connection: set
        where it names none, refused where it names another system."""
        held = connection_base(conn)
        if not held:
            await self.connections.set_base(who.tenant_id, conn.id, address, actor=who.name, at=self.clock())
        elif held.rstrip("/") != address.rstrip("/"):
            # One connection holds one address: a second system, or another path on the same host, is its own app.
            raise ValidationFailed(f"{conn.name} serves {held}; this source is {address}. Pick its own connection.")

    async def _address(self, tenant_id: str, m: Aggregate) -> str:
        conn = await self.connections.get(tenant_id, cid) if (cid := m["connection_id"]) else None
        return connection_base(conn) if conn else ""

    async def create_blank(self, who: Caller, i: BlankModuleIn) -> ModuleDetail:
        _can(who, "tools", "create", what="tools")
        template = _provisioned(who, i)
        name = _kebab(i.name)
        if not i.display_name.strip():
            raise ValidationFailed("Give the module a display name.")
        if not name:
            raise ValidationFailed("Give the module a name, e.g. servicenow.")
        if not await self._name_free(who, name):
            raise Conflict(f"A module named {name} already exists.")
        owner = self.dir.owner_group(who.team) or "Platform"
        conn = await self._usable_connection(who, i.connection_id, None)
        m = blank(
            module_id=new_id("mod"),
            tenant_id=who.tenant_id,
            team_id=who.team.id,
            owner=owner,
            me=who.name,
            at=self.clock(),
            input={"displayName": i.display_name, "name": name, "description": i.description or ""},
        )
        if conn is not None:
            # A custom app's tools are paths on its connection's base address: it is the module's only one.
            base = connection_base(conn)
            host = urlsplit(base).hostname
            await self.hold_unless_listed(who, host, conn.name)
            m.update(
                connection_id=conn.id,
                auth=module_auth(conn),
                catalog_id=conn.catalog_id,
                egress_hosts=[host] if host else [],
            )
        _provision(m, template)
        return await self._detail(await self._create(m), who.team, who)

    # ── Editing ───────────────────────────────────────────────────────────

    async def update_details(self, who: Caller, module_id: str, patch: ModuleDetailsPatchIn) -> ModuleDetail:
        _can(who, "tools", "edit", what="tools")
        levels = await self._levels(who.tenant_id, who.team)
        m = await self._changeable(who, module_id)
        if patch.display_name is not None:
            if not patch.display_name.strip():
                raise ValidationFailed("Give the module a display name.")
            m["display_name"] = patch.display_name.strip()
        if patch.description is not None:
            m["description"] = patch.description.strip()
        if patch.sign_in is not None:
            conn = await self.connections.get(who.tenant_id, cid) if (cid := m["connection_id"]) else None
            if conn is not None:
                sign_in_fits(str(patch.sign_in), conn)
            m["sign_in"] = sign_in_of(patch.sign_in)
        _provision(m, _provisioned(who, patch))
        return await self._detail(await self._save(m), who.team, who, levels=levels)

    def _stage(self, m: Aggregate, changes: list[Change]) -> None:
        pending: list[Change] = list(m["pending"])
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

    async def _append(self, who: Caller, m: Aggregate, ops_in: list[DiscoveredOperation]) -> None:
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

    async def add_operation(self, who: Caller, module_id: str, h: HttpOperationIn) -> ModuleDetail:
        _can(who, "tools", "edit", what="tools")
        m = await self._changeable(who, module_id)
        conn = await self.connections.get(who.tenant_id, cid) if (cid := m["connection_id"]) else None
        op, origin = self._http_operation(h, connection_base(conn) if conn else "")
        await self.hold_unless_listed(who, urlsplit(origin).hostname, conn.name if conn else m["display_name"])
        if conn is None:
            # A blank module's first tool with an address makes the connection that address lives on, so a
            # code module never gets an empty app.
            conn = await self._open_connection(who, m["display_name"], origin, m["team_id"])
            m.update(connection_id=conn.id, auth=module_auth(conn))
        elif not connection_base(conn):
            await self.connections.set_base(who.tenant_id, conn.id, origin, actor=who.name, at=self.clock())
        host = urlsplit(origin).hostname
        if host and host not in m["egress_hosts"]:
            m["egress_hosts"] = [*m["egress_hosts"], host]
        await self._append(who, m, [op])
        return await self._detail(await self._save(m), who.team, who)

    async def set_connection(self, who: Caller, module_id: str, connection_id: str | None) -> ModuleDetail:
        _can(who, "tools", "edit", what="tools")
        levels = await self._levels(who.tenant_id, who.team)
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
                raise Conflict(f"{conn.name} is revoked. Reconnect it in Connections or pick another one.")
            if not may_use(conn, m["team_id"]):
                raise ValidationFailed(f"{conn.name} is not available to this module's team. Pick another one.")
            sign_in_fits(sign_in_of(m.get("sign_in")), conn)
            m.update(connection_id=conn.id, catalog_id=conn.catalog_id, auth=module_auth(conn))
        return await self._detail(await self._save(m), who.team, who, levels=levels)

    def _holders(self, m: Aggregate) -> list[str]:
        return list(dict.fromkeys(a["workflow_name"] for a in self._approvals(m) if a["status"] == "approved"))

    async def remove(self, who: Caller, module_id: str) -> None:
        _can(who, "tools", "delete", what="tools")
        m = await self._changeable(who, module_id, "delete")
        holders = self._holders(m)
        if holders:
            verb, them = ("holds an approval", "it") if len(holders) == 1 else ("hold approvals", "them")
            raise Conflict(f"{', '.join(holders)} {verb} for this module. Revoke {them} first.")
        await self.store.delete(who.tenant_id, module_id)

    async def bulk_remove(self, who: Caller, ids: list[str]) -> BulkOutcome:
        _can(who, "tools", "delete", what="tools")
        out: BulkOutcome = {"updated": [], "skipped": []}
        for module_id in ids:
            m = await self.store.get(who.tenant_id, module_id)
            if m is None or not self._sees(who, m) or not self._team_owns(who, m):
                out["skipped"].append({"id": module_id, "reason": "Not found"})
                continue
            try:
                _not_a_plugin(m)
                # As a single delete: can() with the module's protection, so an admin removes a system module too.
                _can(
                    who,
                    "tools",
                    "delete",
                    what=str(m["display_name"]),
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
        self, who: Caller, module_id: str, op_id: str, patch: OperationPatchIn, fields: set[str]
    ) -> ModuleDetail:
        """`fields` names the keys the caller sent, so `binding: null` (remove it) differs from leaving it out."""
        _can(who, "tools", "edit", what="tools")
        levels = await self._levels(who.tenant_id, who.team)
        m = await self._changeable(who, module_id)
        o = next((x for x in m["operations"] if x["id"] == op_id), None)
        if o is None:
            raise NotFound("Operation")
        _refuse_during_review(m, "edit operations")
        # Read through the dump: the attribute is deprecated, and reading it warns on every edit.
        flag = patch.model_dump(include={"requires_approval"})["requires_approval"]
        two = int(o.get("approvers") or 1) > 1 and patch.approvers != 1
        if flag is False and two:
            raise Unprocessable("An operation two people approve always needs a person's approval.")
        if flag is not None and "approval_mode" not in fields and (patch.access or o["access"]) == "write":
            # The older flag still arrives from callers; the resolver reads only approval_mode, so it is stored as that:
            # true asks a reviewer, false hands the answer back to the app and team.
            patch = patch.model_copy(update={"approval_mode": "reviewer" if flag else None})
            fields = fields | {"approval_mode"}
        mode = patch.approval_mode if "approval_mode" in fields else o.get("approval_mode")
        if mode is not None and (patch.access or o["access"]) != "write":
            raise Unprocessable("Only a write has an approval mode; a read never waits.")
        if mode in ("none", "person") and int(patch.approvers or o.get("approvers") or 1) > 1:
            raise Unprocessable("An operation two people approve always asks a reviewer.")
        rate = patch.rate_limit_per_min
        if rate is not None and not 1 <= rate <= 10_000:
            raise ValidationFailed("Set a rate limit between 1 and 10,000 calls a minute.")
        amount = patch.amount_max
        if amount is not None and (o["access"] != "write" or amount <= 0):
            raise ValidationFailed("Only write operations take an amount limit, and it must be above zero.")
        if amount is not None and not any(f["name"] == "amount" for f in o["input"]):
            # The gateway reads the limit from the `amount` input; on an operation without one it could never hold.
            raise Unprocessable(f"{o['name']} has no amount input, so an amount limit would have nothing to check.")
        approvers = patch.approvers
        if approvers is not None and approvers not in (1, 2):
            raise ValidationFailed("A write is approved by one person or by two different people.")
        team = patch.approver_team
        # The directory is the console seed. A platform team the token names (the demo team) is not in that
        # list; the caller naming their own team is enough (a record belongs to the acting team).
        if team is not None and self.dir.team_by_id(team) is None and team != who.team.id:
            raise Unprocessable(f"{team} is not a team in this workspace.")
        # Stored as the console sends it (bindTo), like the seeded bindings.
        binding: Binding | None = (
            {
                "arg": patch.binding.arg,
                "bindTo": patch.binding.bind_to,
                "mode": patch.binding.mode,
                "required": patch.binding.required,
            }
            if patch.binding is not None
            else None
        )
        new_input = self._field_list(patch.input) if "input" in fields and patch.input is not None else None
        names = {f["name"] for f in (new_input if new_input is not None else o["input"])}
        if binding and binding["arg"] not in names:
            raise ValidationFailed(f"{binding['arg']} is not an input of {o['name']}.")
        shape = self._checked_shape(m, o, patch, fields, await self._address(who.tenant_id, m))
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
        access = patch.access
        answer_before = o.get("approval_mode")
        self._take_baseline(m)
        changes: list[Change] = self._shape_changes(o, shape)
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
            # A read never waits; a read made a write has no approval setting of its own yet, so the team default
            # decides. A requiresApproval in the same patch applies after this.
            o["requires_approval"] = None if access == "write" else False
            if access == "read":
                o["amount_max"] = None
        if patch.enabled is not None and patch.enabled != o["enabled"]:
            # Hiding an operation a workflow is approved for breaks that workflow, so it is a major change.
            users = list(
                dict.fromkeys(
                    a["workflow_name"]
                    for a in self._approvals(m)
                    if a["status"] == "approved" and name in a["operations"]
                )
            )
            if patch.enabled:
                changes.append({"operation": name, "kind": "added", "detail": "Exposed to workflows", "major": True})
            elif users:
                verb = "calls" if len(users) == 1 else "call"
                detail = f"Hidden from workflows; breaks {', '.join(users)}, which {verb} it"
                changes.append({"operation": name, "kind": "removed", "detail": detail, "major": True})
            else:
                detail = "Hidden from workflows; no workflow is approved for it"
                changes.append({"operation": name, "kind": "removed", "detail": detail, "major": False})
            o["enabled"] = patch.enabled
        flag_changed = flag is not None and flag != o.get("requires_approval")
        if flag is not None:
            # Kept as sent for older readers; the approval_mode change below is what is logged and enforced.
            o["requires_approval"] = flag
        if "approval_mode" in fields and mode != o.get("approval_mode"):
            before_mode = o.get("approval_mode")
            # Asking less than the app and team do, or handing the answer back to them, widens what runs unattended:
            # Security reviews it. Asking a reviewer is stricter and publishes as a minor change.
            detail = f"Approval {_MODE_WORDS[before_mode]} → {_MODE_WORDS[mode]}"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": mode != "reviewer"})
            o["approval_mode"] = mode
        elif flag_changed:
            # The stored flag moved but the answer did not (a tool already following its app, told false): still an
            # edit, so a script that re-sends it is not refused as "Nothing changed". No effect on calls, so minor.
            detail = f"Approval {_MODE_WORDS[o.get('approval_mode')]}"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": False})
        if "reviewer_role" in fields and patch.reviewer_role != o.get("reviewer_role"):
            role = patch.reviewer_role
            anyone = "anyone who can approve"
            detail = f"Reviewer role {o.get('reviewer_role') or anyone} → {role or anyone}"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": role is None})
            o["reviewer_role"] = role
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
            if approvers > 1 and o.get("approval_mode") != "reviewer":
                # Asking for two approvers makes the tool ask a reviewer: a write two people approve always waits for
                # them, even one switched to run at once.
                changes.append(
                    {
                        "operation": name,
                        "kind": "settings",
                        "detail": "Every call waits for an approval",
                        "major": False,
                    }
                )
                o["requires_approval"] = True
                o["approval_mode"] = "reviewer"
        if team is not None and team != o.get("approver_team"):
            detail = f"Approved by {team}"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": True})
            o["approver_team"] = team
        # Part of the approval policy, which Security reviews either way (publish compares it with the baseline).
        step_up = patch.step_up
        if step_up is not None and step_up != bool(o.get("step_up")):
            detail = "Approving asks for a step-up" if step_up else "Approving no longer asks for a step-up"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": True})
            o["step_up"] = step_up
        # Off lets a run with nobody behind it sign in with the team's backup account, so Security reviews it.
        needs_person = patch.needs_person
        if needs_person is not None and needs_person != bool(o.get("needs_person")):
            detail = "Signs in as a person only" if needs_person else "No longer signs in as a person only"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": not needs_person})
            o["needs_person"] = needs_person
        # Not reviewed: a scope only asks the person for more consent, and the system decides what a token may do.
        scopes = patch.scopes
        if scopes is not None and list(dict.fromkeys(scopes)) != list(o.get("scopes") or []):
            scopes = list(dict.fromkeys(scopes))
            detail = f"Needs the scopes {', '.join(scopes)}" if scopes else "Needs no scopes beyond the connection's"
            changes.append({"operation": name, "kind": "settings", "detail": detail, "major": False})
            o["scopes"] = scopes
        if patch.description is not None and patch.description.strip() != o["description"]:
            changes.append({"operation": name, "kind": "settings", "detail": "Description edited", "major": False})
            o["description"] = patch.description.strip()
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
        # Writes the operation's example mock under its old name, while the console still sends it; removed in D3c/D3d,
        # when the console writes the example through the mock routes.
        if "stub" in fields:
            stub: JsonValue = {"ok": True} if patch.stub is None else patch.stub
            if len(json.dumps(stub)) > MAX_STUB_BYTES:
                raise ValidationFailed(f"Keep the mock response under {MAX_STUB_BYTES // 1000} KB.")
            if stub != o.get("stub"):
                # Minor, as a transform edit is: it changes what a stub executor and tests answer, not the contract.
                changes.append(
                    {"operation": name, "kind": "settings", "detail": "Mock response edited", "major": False}
                )
                o["stub"] = stub
        if "code" in fields and patch.code is not None:
            changes.extend(self._code_changes(o, _code_settings(patch.code)))
        if not changes:
            raise ValidationFailed("Nothing changed.")
        answer_changed = o.get("approval_mode") != answer_before
        self._stage(m, changes)
        # A tool's own answer reaches agents' kept tool lists only when told: one event with the save.
        told = (
            [policy_changed_event(m, o, who.team.id, who.principal.email if who.principal else None)]
            if answer_changed
            else []
        )
        return await self._detail(await self._save(m, events=told), who.team, who, levels=levels)

    @staticmethod
    def _code_changes(o: Operation, code: CodeSettings) -> list[Change]:
        """Applies a code operation's new settings. A tool or secret it did not have widens what the function reaches,
        so Security reviews it; an edit to the source or the limits alone is minor."""
        if o["executor"] != "code":
            raise ValidationFailed(f"{o['name']} is not a code operation.")
        before = o.get("code")
        if code == before:
            return []
        added = [
            *(set(code["bindings"]) - set((before.get("bindings") or []) if before else [])),
            *(set(code["secrets"]) - set((before.get("secrets") or []) if before else [])),
        ]
        detail = f"May now use {', '.join(sorted(added))}" if added else "Function edited"
        o["code"] = code
        kind = "binding_changed" if added else "settings"
        return [{"operation": o["name"], "kind": kind, "detail": detail, "major": bool(added)}]

    async def add_function(self, who: Caller, module_id: str, f: CodeOperationIn) -> ModuleDetail:
        """Adds a function to a code module."""
        _can(who, "tools", "edit", what="tools")
        levels = await self._levels(who.tenant_id, who.team)
        m = await self._changeable(who, module_id)
        if kind_of(m) != "code" or m["connection_id"]:
            raise ValidationFailed(f"{m['display_name']} is not a code module; add its operations from its system.")
        await self._append(who, m, [_code_operation(f)])
        return await self._detail(await self._save(m), who.team, who, levels=levels)

    def _checked_shape(
        self, m: Aggregate, o: Operation, patch: OperationPatchIn, fields: set[str], base: str
    ) -> CallShape:
        """The call-shape fields this patch sets, validated as add validates them; nothing is applied here."""
        sent: CallShape = {}
        if "method" in fields:
            sent["method"] = patch.method
        if "path" in fields:
            sent["path"] = patch.path
        if "headers" in fields:
            sent["headers"] = (
                None if patch.headers is None else [{"key": h.key, "value": h.value} for h in patch.headers]
            )
        if "body" in fields:
            sent["body"] = patch.body
        if "body_encoding" in fields:
            sent["body_encoding"] = patch.body_encoding
        if "response_transform" in fields:
            sent["response_transform"] = patch.response_transform
        if "timeout_ms" in fields:
            sent["timeout_ms"] = patch.timeout_ms
        if not sent:
            return {}
        if o["executor"] != "http":
            raise ValidationFailed(f"{o['name']} is not an HTTP operation; its call comes from its server or seed.")
        for k in ("method", "path", "headers"):
            if k in sent and sent.get(k) is None:
                raise ValidationFailed(f"An HTTP operation keeps a {k}.")
        # Every problem is found before any is reported, so one save lists them all.
        problems: list[str] = []
        if "path" in sent:
            path = str(sent["path"]).strip()
            if not path.startswith("/"):
                problems.append("Enter the path after the module endpoint, starting with /.")
            elif not base:
                problems.append("Set the app's address on its connection before editing a path.")
            else:
                try:
                    sent["path"] = self._split_url(base.rstrip("/") + path, base)[1]
                except ValidationFailed as e:
                    problems.append(e.message)
        if "headers" in sent:
            sent["headers"] = self._checked_headers(sent["headers"] or [], problems)
        if "body" in sent:
            sent["body"] = (sent["body"] or "").strip() or None
        if "body" in sent or "body_encoding" in sent or "headers" in sent:
            body, encoding = sent.get("body", o.get("body")), sent.get("body_encoding", o.get("body_encoding"))
            headers = sent["headers"] if "headers" in sent else o.get("headers") or []
            if problem := self._encoding_problem(body, encoding, headers or []):
                problems.append(problem)
        if "response_transform" in sent:
            sent["response_transform"] = (sent["response_transform"] or "").strip() or None
            if sent["response_transform"] and (problem := transform.problem(sent["response_transform"])):
                problems.append(problem)
        limit = sent.get("timeout_ms")
        if limit is not None and not 1_000 <= limit <= 120_000:
            problems.append("Set a timeout between 1 and 120 seconds (1000 to 120000 ms).")
        refuse(problems)
        changed: CallShape = {}
        if "method" in sent and sent["method"] != o.get("method"):
            changed["method"] = sent["method"]
        if "path" in sent and sent["path"] != o.get("path"):
            changed["path"] = sent["path"]
        if "headers" in sent and sent["headers"] != o.get("headers"):
            changed["headers"] = sent["headers"]
        if "body" in sent and sent["body"] != o.get("body"):
            changed["body"] = sent["body"]
        if "body_encoding" in sent and sent["body_encoding"] != o.get("body_encoding"):
            changed["body_encoding"] = sent["body_encoding"]
        if "response_transform" in sent and sent["response_transform"] != o.get("response_transform"):
            changed["response_transform"] = sent["response_transform"]
        if "timeout_ms" in sent and sent["timeout_ms"] != o.get("timeout_ms"):
            changed["timeout_ms"] = sent["timeout_ms"]
        return changed

    @staticmethod
    def _shape_changes(o: Operation, shape: CallShape) -> list[Change]:
        """Applies a validated call-shape edit to `o` and says what changed. A new method, path or body changes the
        contract a workflow was approved against, so it is major; headers, the transform and the timeout are minor."""
        if not shape:
            return []
        name = o["name"]
        out: list[Change] = []
        contract = [k for k in ("method", "path", "body", "body_encoding") if k in shape]
        if contract:
            before = f"{o['method']} {o['path']}"
            after = f"{shape.get('method', o['method'])} {shape.get('path', o['path'])}"
            detail = f"Call {before} → {after}" if before != after else "Call unchanged"
            if "body" in shape or "body_encoding" in shape:
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
        if "method" in shape:
            o["method"] = shape["method"]
        if "path" in shape:
            o["path"] = shape["path"]
        if "headers" in shape:
            o["headers"] = shape["headers"] or []
        if "body" in shape:
            o["body"] = shape["body"]
        if "body_encoding" in shape:
            o["body_encoding"] = shape["body_encoding"]
        if "response_transform" in shape:
            o["response_transform"] = shape["response_transform"]
        if "timeout_ms" in shape:
            o["timeout_ms"] = shape["timeout_ms"]
        # A placeholder the new path or body names becomes an input; fields nothing names stay, and the console warns.
        named = [*URL_VAR.findall(o["path"] or ""), *BODY_VAR.findall(o.get("body") or "")]
        have = {f["name"] for f in o["input"]}
        o["input"] = [*o["input"], *(_sample_field(n) for n in dict.fromkeys(named) if n not in have)]
        return out

    @staticmethod
    def _field_list(fields: Sequence[SchemaFieldIn]) -> list[InputField]:
        """The input fields as stored: trimmed text, and unset optional parts left out."""
        out: list[InputField] = []
        for f in fields:
            row: InputField = {"name": str(f.name).strip(), "type": f.type, "required": bool(f.required)}
            if f.description not in (None, ""):
                row["description"] = str(f.description).strip()
            if f.format not in (None, ""):
                row["format"] = str(f.format).strip()
            if f.example not in (None, ""):
                row["example"] = str(f.example).strip()
            if f.enum:
                row["enum"] = [str(v).strip() for v in f.enum]
            if f.default is not None:
                row["default"] = f.default
            out.append(row)
        return out

    @staticmethod
    def _check_input(
        o: Operation,
        fields: list[InputField],
        *,
        path: str | None,
        body: str | None,
        binding: Binding | None,
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
    def _input_changes(o: Operation, fields: list[InputField]) -> list[Change]:
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
        out: list[Change] = []
        if major:
            out.append({"operation": name, "kind": "schema_changed", "detail": "; ".join(major), "major": True})
        elif minor:
            out.append({"operation": name, "kind": "schema_changed", "detail": "; ".join(minor), "major": False})
        if not major and not minor and [f["name"] for f in o["input"]] != list(after):
            out.append({"operation": name, "kind": "schema_changed", "detail": "Fields reordered", "major": False})
        return out

    async def publish(self, who: Caller, module_id: str, note: str) -> ModuleDetail:
        _can(who, "tools", "publish", what="tools")
        m = await self._owned(who, module_id)
        _not_a_plugin(m)
        reviewed_change = _differs_from_published(m)
        if not m["pending"] and not reviewed_change:
            raise ValidationFailed("There are no changes to publish.")
        if not note.strip():
            raise ValidationFailed("Say what changed.")
        _refuse_during_review(m, "publish another version")
        major = reviewed_change or any(c["major"] for c in m["pending"])
        # "always" sends every version to a review; "major" and "never" send a major one only, since every major
        # change to a tool module touches what it calls, how a write is approved, or where it reaches.
        mode = (
            await self.publish_policy.mode(who.tenant_id, m["team_id"] or "")
            if self.publish_policy
            else ToolsMode("major")
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
            m["versions"] = [self._deprecated(v) if v["status"] == "published" else v for v in m["versions"]]
        m["versions"] = [
            *m["versions"],
            {
                **version_defaults(),
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
            review_id = await self._open_review(who, m, version, m["versions"][-1]["changes"], note, security=major)
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
        changes: list[Change],
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
            # The diff names the hosts a path reaches, which hang off the app's address on its connection.
            module={**m, "endpoint": await self._address(who.tenant_id, m)},
            version=version,
            changes=changes,
            note=note.strip(),
            security=security,
        )

    async def discard(self, who: Caller, module_id: str) -> ModuleDetail:
        _can(who, "tools", "edit", what="tools")
        levels = await self._levels(who.tenant_id, who.team)
        m = await self._changeable(who, module_id)
        _refuse_during_review(m, "discard changes")
        if m["baseline"] is None:
            raise ValidationFailed("There are no changes to discard.")
        restored = [restored_operation(o) for o in published_operations(m["baseline"])]
        m.update(operations=restored, pending=[], baseline=None)
        return await self._detail(await self._save(m), who.team, who, levels=levels)

    async def request_review(self, who: Caller, module_id: str, note: str) -> ModuleDetail:
        _can(who, "tools", "publish", what="tools")
        m = await self._owned(who, module_id)
        _not_a_plugin(m)
        if any(v["status"] == "in_review" for v in m["versions"]):
            raise Conflict("A security review is already open for this module.")
        if not m["operations"]:
            raise Unprocessable("Add at least one operation before requesting a security review.")
        last = m["versions"][-1]
        changes = last["changes"] or [{"operation": "*", "kind": "settings", "detail": "First review", "major": True}]
        review_id = await self._open_review(who, m, m["version"], changes, note)
        if m["status"] == "draft":
            m["status"] = "in_review"
        status = "in_review" if last["status"] == "draft" else last["status"]
        reviewed: Version = {
            **last,
            "review_id": review_id,
            "requested_at": self.clock(),
            "finding": None,
            "reviewer": None,
            "status": status,
        }
        m["versions"] = [*m["versions"][:-1], reviewed]
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
    ) -> ModuleDetail:
        """A decision made in Reviews, sent by agents-service, which already held it to the review rules: not
        the requester, not the saver, Security for a security change, a reason for a no. Approving the module's
        current version publishes it and clears drift, since the reviewed tool list is the one now held; a no sends a
        module never published back to draft, and withdraws the declined version of a published one. Applying the same
        decision twice changes nothing."""
        levels = await self._levels(tenant_id, self.dir.everyone)
        m = await self.store.get_any(tenant_id, module_id)
        if m is None:
            raise NotFound("Module")
        v = next((x for x in m["versions"] if x["version"] == version and x.get("review_id") == request_id), None)
        if v is None:
            raise NotFound("Review")
        if v["status"] != "in_review":
            return await self._detail(m, self.dir.everyone, levels=levels)
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
        return await self._detail(await self._save(m), self.dir.everyone, levels=levels)

    # ── Workflow approvals ────────────────────────────────────────────────

    async def request_approval(self, who: Caller, module_id: str, i: ApprovalRequestIn) -> ApprovalView:
        _can(who, "tools", "edit", what="tools")
        m = await self._find(who, module_id)
        _not_a_plugin(m)
        if m["status"] == "draft":
            raise Conflict("Submit the module for security review before workflows can request it.")
        wf = (await self.workflows.all(who.tenant_id)).get(i.workflow_id)
        if wf is None:
            raise ValidationFailed("Choose a workflow.")
        if not wf.team_id:
            # Fail closed: a workflow no team owns has no one the grant would be for.
            raise Unprocessable(f"{wf.name} belongs to no team, so no team can be granted access for it.")
        # The workflow's platform team, which the dev seed need not hold: the grant is for that team id.
        owner = self.dir.team(wf.team_id)
        if not i.operations:
            raise ValidationFailed("Choose at least one operation.")
        # The default policy: the module's team decides, unless an operation asked for names its own approving team.
        decider = next(
            (o["approver_team"] for o in m["operations"] if o["name"] in i.operations and o.get("approver_team")),
            m["team_id"],
        )
        if decider is None:
            # A workspace-level module (the platform's tools) serves every team's runs with no grant, and no team
            # would decide a request for it.
            raise Unprocessable(
                f"{m['display_name']} belongs to no team: every team's workflows may already use it, so there is "
                "nothing to request."
            )
        production = i.environment == "production"
        most = 365 if production else 90
        if not 1 <= i.expires_in_days <= most:
            raise ValidationFailed(f"{'Production' if production else 'Test'} approvals last at most {most} days.")
        if len(i.justification.strip()) < 10:
            raise ValidationFailed("Explain why the workflow needs these operations.")
        name = wf.name
        if any(a["workflow_id"] == i.workflow_id and a["status"] == "requested" for a in self._approvals(m)):
            raise Conflict(f"{name} already has an open request for this module.")
        now = self.clock()
        approval_id = new_id("apr")
        a: Approval = {
            "id": approval_id,
            "workflow_id": i.workflow_id,
            "workflow_name": name,
            "workflow_team_id": owner.id,
            "environment": i.environment,
            "major": major_of(m["version"]),
            "operations": i.operations,
            "constraints": None,
            "requested_by": who.name,
            # Who asked, as the token names them: the requester rule compares it, never the display name.
            "requested_by_email": who.principal.email if who.principal else None,
            "justification": i.justification.strip(),
            "requested_at": now,
            "decided_by": None,
            "decided_at": None,
            "status": "requested",
            "expires_at": now + timedelta(days=i.expires_in_days),
            "reason": None,
            # Decided in Human Tasks by `decider`; who in that team may decide is can(reviews.decide), as for
            # any review.
            "decider_team": decider,
            # The system workflow's run key: the module page opens its review in Human Tasks by it.
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
    ) -> ApprovalView:
        """A tool access review's decision from Human Tasks, applied to the module's approval: approved grants
        it, anything else ends the request. Applying the same decision again changes nothing; a request already ended
        another way (revoked, or decided otherwise) is refused, so a late approval never revives a revoked grant."""
        m = await self.store.get_any(tenant_id, module_id)
        if m is None:
            raise NotFound("Tool module")
        a = next((x for x in m["approvals"] if x["id"] == approval_id), None)
        if a is None:
            raise NotFound("Approval")
        if team_id is not None and a.get("decider_team") not in (None, team_id):
            # The system workflow runs in the deciding team; a run in another team decides nothing here.
            raise Forbidden("This request is decided by another team.", code="team_forbidden")
        asker = str(a.get("requested_by_email") or "")
        if asker and asker.casefold() in {str(d).casefold() for d in (*deciders, by or "")}:
            # Separation of duties through can(requested_by=), with requesterMayDecide read now rather than from a
            # token: the asker decides their own request only while it is on.
            may_decide = self.requester_policy is not None and await self.requester_policy.allowed(tenant_id)
            refused = own_request_refusal(
                Access(),
                tenant_id,
                asker,
                (*deciders, by),
                may_decide=may_decide,
                team_id=a.get("decider_team"),
                what="this access",
            )
            if refused is not None:
                raise refused
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
    ) -> ApprovalView:
        m = await self._owned(who, module_id)
        a = next((x for x in m["approvals"] if x["id"] == approval_id), None)
        if a is None:
            raise NotFound("Approval")
        if a.get("review_id"):
            # Decided in Human Tasks with every other review; this route only ends requests made before then.
            raise Conflict(f"Decide this request in Human Tasks ({a['review_id']}).", code="decided_in_reviews")
        _can(
            who,
            "tools",
            "decide",
            what="this tool approval",
            requested_by=(a.get("requested_by_email"),),
        )
        if a["status"] != "requested":
            raise Conflict("This request was already decided.")
        if decision == "rejected" and not (reason or "").strip():
            raise ValidationFailed("Give a reason for the rejection.")
        a.update(status=decision, decided_by=who.name, decided_at=self.clock(), reason=(reason or "").strip() or None)
        await self._save(m, touch=False)
        return self._approval_out(a)

    async def revoke_approvals(self, who: Caller, module_id: str, ids: list[str], reason: str) -> BulkOutcome:
        _can(who, "tools", "decide", what="tool approvals")
        m = await self._owned(who, module_id)
        if not reason.strip():
            raise ValidationFailed("Give a reason.")
        out: BulkOutcome = {"updated": [], "skipped": []}
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

    async def test(self, who: Caller, module_id: str, i: TestRun) -> TestResult:
        """What the gateway would decide for this call in this run context, and the answer when it allows. On the
        sandbox target, the console's Real, the call is a gateway call: the same approval, limits, egress,
        account choice and call log as an agent's, in the environment the person picked; on the stub target, Mock,
        nothing leaves the gateway.
        The `owner` context is the module's own team trying it (whoever passes the module's team guard): no workflow
        approval is needed and a bound field takes the value typed. A workflow's context needs that
        workflow's approval and, for a write that asks for one, an approval token, which a test run never makes up
        (ADR-0005)."""
        if who.principal is not None and who.principal.kind == "api_key":
            # A key's tools.run is for the gateway's call path over MCP; the test console is a person's page.
            raise Forbidden("An API key runs tools over MCP, not the test console.", code="role_required")
        _can(who, "tools", "run", what="tools")
        # Trying a tool is its owners' authoring page: a team holding only a workflow's grant calls it through the
        # gateway's /v1/calls, never through the owner context here.
        m = await self._owned(who, module_id)
        o = next((x for x in m["operations"] if x["name"] == i["operation"]), None)
        if o is None:
            raise NotFound("Operation")
        owner = i["context_id"] == OWNER_CONTEXT
        ctx = None if owner else next((c for c in self._run_contexts() if c["id"] == i["context_id"]), None)
        if ctx is None and not owner:
            raise ValidationFailed("Choose a run context.")
        call_id = new_id("test")
        sandbox = i["target"] == "sandbox"

        def deny(reason: str) -> TestResult:
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
        args: Json = dict(i["input"])
        bound: list[BoundValue] = []
        b = o["binding"]
        if b:
            value = ctx["bindings"].get(b["bindTo"]) if ctx else None
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
                "output": {"error": "invalid_input", "missing": [*missing]},
                "masked": [],
                "callId": call_id,
            }
        if amount_refusal(o, args) is not None:  # the gateway's own check (ops_tools.limits)
            return deny("constraint")
        would_pause = o["access"] in WRITES and bool(
            (
                await self.approvals.answer(
                    who.tenant_id,
                    who.team.id,
                    m,
                    access=o["access"],
                    setting=tool_mode(o),
                    reviewer_role=o.get("reviewer_role"),
                    approvers=approval_policy(m, o)["approvers"],
                    test_account=bool(m.get("sandbox")),
                    channel="test",
                    tool=o["name"],
                )
            )["waits"]
        )
        # A real write in a workflow's context needs a real approval; simulate_approval stands in for one on Mock only.
        if would_pause and sandbox and ctx is not None:
            return deny("approval_token_missing")
        # The workbench's draft transform and mock run in place of the operation's for this test only: nothing
        # is staged, so what agents get changes only through staging and publishing.
        draft: TestDraft = i.get("draft") or {}
        if "stub" in draft and len(json.dumps(draft["stub"])) > MAX_STUB_BYTES:
            raise ValidationFailed(f"Keep the mock response under {MAX_STUB_BYTES // 1000} KB.")
        template = draft["response_transform"] if "response_transform" in draft else o.get("response_transform")
        mock = draft["stub"] if "stub" in draft and draft["stub"] is not None else o.get("stub")
        trial = Trial()
        trial.note("Input checked against the operation's schema")
        out: TestResult = {
            "decision": "allow",
            "status": 200,
            "latencyMs": 0,
            "bound": bound,
            "wouldPause": would_pause,
            "output": masked(mock, o["masked_output"]),
            "masked": o["masked_output"],
            "callId": call_id,
        }
        if would_pause and i.get("simulate_approval") and not sandbox:
            out["testApprovalToken"] = new_id("test-apt")
        answer = (
            await self.mocks.for_call(who.tenant_id, m["id"], o["name"], args, TEST) if "stub" not in draft else None
        )
        # A plain Mock run answers the saved example, the tool's answer as an agent gets it, already shaped: the
        # transform reads the system's raw answer and is not applied to it. A workbench run trying a drafted sample
        # or transform does apply it, which is what it is for.
        example = not sandbox and answer is None and not {"stub", "response_transform"} & draft.keys()
        if sandbox and o.get("executor") in ("http", "mcp", "plugin") and self.real_runs is not None:
            out.update(
                await self._real_call(
                    who,
                    m,
                    o,
                    args,
                    secret_values=i.get("secret_values"),
                    trial=trial,
                    environment=str(i.get("environment") or TEST),
                    confirmed=bool(i.get("confirmed")),
                )
            )
        elif answer is not None:
            # A mock answer the test environment holds for this input, as a test run would get it.
            await self.mocks.wait(answer, o.get("timeout_ms") or m["timeout_ms"])
            status = 504 if answer["timeout"] else int(answer["status"])
            out.update(status=status, output=masked(answer.get("body"), o["masked_output"]), mockId=answer["id"])
            trial.note(f"Answered from the mock answer {answer['name']}")
        else:
            trial.note("Answered from the example" if example else "Answered from the mock response")
        raw = out["output"]
        # A plugin tool's Real answer comes back shaped by the gateway, which alone holds the team's settings its
        # transform reads; the answer before it is the trial's.
        shaped_by_gateway = sandbox and str(m.get("template_id") or "").startswith("plugin:")
        out["rawResponse"] = trial.raw if shaped_by_gateway and trial.raw is not None else raw
        if template and out["status"] < 400 and not example and not shaped_by_gateway:
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

    async def _real_call(
        self,
        who: Caller,
        module: Module,
        op: Operation,
        args: Json,
        *,
        secret_values: dict[str, str] | None,
        trial: Trial,
        environment: str,
        confirmed: bool = False,
    ) -> TestResult:
        """The Real run, as one gateway call: the gateway decides it as it decides an agent's call (approval,
        limits, egress, the team's account) in the environment the person chose, and logs it under them. `trial` comes
        back with the request as sent, secrets hidden; `secret_values` stand in for unset secrets for this call only.
        A test environment holding a saved mock answer for this input answers from it, as an agent's call would."""
        if self.real_runs is None or who.principal is None:
            raise NotYetAvailable("This service runs no Real calls from a tool page.")
        started = time.perf_counter()
        ran = await self.real_runs(
            who.principal,
            tool=op["name"],
            args=args,
            environment=environment,
            act=f"console:{who.name}",
            trial=trial,
            secret_values=secret_values,
            confirmed=confirmed,
        )
        result: TestResult = {
            "callId": ran["callId"],
            "latencyMs": round((time.perf_counter() - started) * 1000),
            "reachedHost": urlsplit(await self._address(str(module["tenant_id"]), module)).hostname,
            "stubbed": False,
        }
        if "code" in ran:
            message = "; ".join(ran["reasons"])
            code = ran["code"]
            if code == "gateway_refused" and any("needs an approval token" in r for r in ran["reasons"]):
                # A live-account test run waiting for the person's yes reads as a missing approval, like a workflow's.
                code = "approval_token_missing"
            return {
                **result,
                "decision": "deny",
                "denyReason": code,
                "denyMessage": message,
                "status": ran["status"],
                "output": {"error": ran["code"], "message": message},
            }
        result["output"] = ran["output"]
        if not ran["ok"]:
            answer = narrow.an_object(ran["output"], "A failed call's answer")
            error = narrow.an_object(answer.get("error") or {}, "A failed call's error")
            # The upstream's own status when it answered; otherwise the gateway's, by whether the call timed out.
            result["status"] = narrow.field(error, "status", int) or (
                504 if "TIMEOUT" in str(error.get("code")) else 502
            )
        return result

    # ── Not in this card ──────────────────────────────────────────────────

    async def _connection_ok(self, tenant_id: str, connection_id: str | None) -> None:
        if not connection_id:
            return
        conn = await self.connections.get(tenant_id, connection_id)
        if conn is None:
            raise ValidationFailed("That connection no longer exists. Pick another one.")
        if status_of(conn, self.clock()) == "revoked":
            raise Conflict(f"{conn.name} is revoked. Reconnect it in Connections first.")

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

    async def _discover(self, who: Caller, source: ModuleSourceIn, module_connection: str | None = None) -> Discovered:
        """`source`, read now. Its own connection is used when it names one, else `module_connection`, the module's."""
        connection_id = source.connection_id if source.connection_id is not None else module_connection
        await self._connection_ok(who.tenant_id, connection_id)
        if source.kind == "openapi":
            if not source.spec_url:
                if source.file_id or source.file_name:
                    raise NotYetAvailable("Importing an uploaded document is not available yet; give its URL.")
                raise ValidationFailed("Add the spec as a URL.")
            raw = await self._fetch(who, source.spec_url)
            try:
                text = raw.decode()
                spec: JsonValue = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
                return openapi.discover(spec, source.spec_url)
            except (UnicodeDecodeError, ValueError, yaml.YAMLError) as e:
                raise ValidationFailed(f"The document could not be read: {e}"[:300]) from e
        if not source.url:
            raise ValidationFailed("Enter the MCP server's https address.")
        return await self._discover_mcp(who, source.url, connection_id)

    async def _signed_in_headers(self, who: Caller, connection_id: str | None, url: str) -> tuple[dict[str, str], Any]:
        """A discovery's sign-in through the named connection, in the test environment: its headers and its
        client certificate; nothing for no connection."""
        if not connection_id or self.auth is None:
            return {}, None
        conn = await self.connections.get(who.tenant_id, connection_id)
        if conn is not None and conn.auth_kind == "none":
            # A module's own open connection holds only its address: there is nothing to sign in with.
            return {}, None
        probe: ModuleRef = {
            "tenant_id": who.tenant_id,
            "connection_id": connection_id,
            "team_id": who.team.id,
            "endpoint": url,
        }
        try:
            prepared = await self.auth.prepare(probe, TEST, tool="discovery", actor=who.name)
        except AuthFailed as e:
            raise ValidationFailed(
                str(e), code="sign_in_required" if e.code == "NOT_SIGNED_IN" else "connection"
            ) from e
        return (prepared.headers, prepared.certificate) if prepared else ({}, None)

    async def _discover_mcp(self, who: Caller, url: str, connection_id: str | None = None) -> Discovered:
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
    def _public(result: Discovered) -> PublicDiscovered:
        """The console's DiscoveryResult: an operation's headers stay on the service until import."""
        ops: list[PublicOperation] = [
            {
                "name": o["name"],
                "description": o["description"],
                "access": o["access"],
                "method": o["method"],
                "path": o["path"],
                "group": o["group"],
                "input": o["input"],
            }
            for o in result["operations"]
        ]
        return {**result, "operations": ops}

    async def discover(self, who: Caller, source: ModuleSourceIn) -> PublicDiscovered:
        _can(who, "tools", "create", what="tools")
        return self._public(await self._discover(who, source))

    @staticmethod
    def _chosen(found: Discovered, chosen: Sequence[DiscoveredOperation]) -> list[DiscoveredOperation]:
        """The caller's picks as the source describes them: name and the confirmed access class from the caller,
        everything else from the source. A name the source does not list is refused."""
        listed = {o["name"]: o for o in found["operations"]}
        unknown = [o["name"] for o in chosen if o["name"] not in listed]
        if unknown:
            raise ValidationFailed(f"{', '.join(unknown)} is not in the source.")
        executor = "mcp" if found["type"] == "mcp" else "http"
        return [{**listed[o["name"]], "access": o["access"], "executor": executor} for o in chosen]

    async def import_operations(self, who: Caller, module_id: str, i: ImportOperationsIn) -> ModuleDetail:
        """Appends the chosen operations as the source describes them now; the caller picks which, and confirms each
        one's access class, but never supplies their method, path, inputs or headers."""
        _can(who, "tools", "create", what="tools")
        m = await self._changeable(who, module_id)
        chosen = [_picked(o) for o in i.operations]
        if not chosen:
            raise ValidationFailed("Choose at least one operation to import.")
        found = await self._discover(who, i.source, m["connection_id"])
        fresh = [o for o in self._chosen(found, chosen) if not any(x["name"] == o["name"] for x in m["operations"])]
        if not fresh:
            raise Conflict("Every chosen operation is already in this module.")
        held = await self._address(who.tenant_id, m)
        if held and held.rstrip("/") != found["endpoint"]:
            raise Conflict(f"This module calls {held}; the source serves {found['endpoint']}.")
        if m["connection_id"] is None:
            conn = await self._open_connection(who, m["display_name"], found["endpoint"], m["team_id"])
            m.update(connection_id=conn.id, auth=module_auth(conn))
        elif not held:
            conn = await self.connections.get(who.tenant_id, m["connection_id"])
            if conn is not None:
                await self._address_on(who, conn, found["endpoint"])
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
