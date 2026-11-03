"""Wire models for `/v1/tool-modules`, mirroring apps/console/src/lib/types/tool-modules.ts field for field.

Responses are built as dicts and returned through `ok()`; these models document them in openapi.json, and the tests'
contract checker validates every response against that document, so a field added on one side fails a test."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_service_kit.http import ListResult, Out

from ..environments import ConnectionEnvironment, ModuleEnvironment

Access = Literal["read", "write"]
ModuleType = Literal["mcp", "openapi", "http", "code"]
Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
# How an operation's body is sent; none is json.
BodyEncoding = Literal["json", "form", "raw"]
# Whose account a module's calls may sign in with; a connection whose sign-in does not fit is refused.
ModuleSignIn = Literal["team", "person", "person_or_team"]
# `either`, the earlier name, is still taken on input for one release and stored as person_or_team.
ModuleSignInIn = Literal["team", "person", "person_or_team", "either"]
Environment = ModuleEnvironment
BindingSource = Literal["case.account", "case.customerId", "case.id", "case.requesterEmail", "case.queue"]
ChangeKind = Literal["added", "removed", "access_widened", "schema_changed", "binding_changed", "settings"]
FieldType = Literal["string", "number", "integer", "boolean", "object", "array"]


class In(BaseModel):
    """Request bodies refuse unknown fields, so a caller cannot slip in a field the route never reads."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# Shared parts


class SchemaField(Out):
    name: str
    type: FieldType
    required: bool
    description: str | None = None
    format: str | None = None
    enum: list[str] | None = None
    example: str | None = None
    # Sent when a call leaves this optional field out.
    default: str | int | float | bool | None = None


class SubjectBinding(Out):
    arg: str
    bind_to: BindingSource
    mode: Literal["equals", "within"]
    required: bool


class ModuleRef(Out):
    id: str
    name: str


class ConnectionRef(Out):
    id: str
    name: str
    kind: str
    status: Literal["draft", "healthy", "needs_reconnect", "expiring", "revoked", "error"]
    expires_at: str | None = None
    # The connection's base address by environment (test, production), where the module's paths go.
    base_urls: dict[str, str] = Field(default_factory=dict[str, str])


class OperationChange(Out):
    operation: str
    kind: ChangeKind
    detail: str
    major: bool


# Responses


class PendingReview(Out):
    id: str
    version: str
    requested_by: str
    requested_at: str


class ToolModule(Out):
    id: str
    name: str
    display_name: str
    system: str
    description: str
    type: ModuleType
    status: Literal["draft", "in_review", "published", "revoked"]
    version: str
    major: int
    owner_team: str
    endpoint: str
    operation_count: int
    access_classes: list[Access]
    approval_state: Literal["draft", "approved", "needs_approval", "expiring", "expired"]
    next_expiry: str | None = None
    pending_approvals: int
    workflows: list[ModuleRef]
    calls24h: int = Field(alias="calls24h")
    error_rate: float
    p95_ms: int = Field(alias="p95Ms")
    reachable: bool
    drift: bool
    connection_id: str | None = None
    connection: ConnectionRef | None
    sign_in: ModuleSignIn = "person_or_team"
    updated_at: str
    # The review waiting on Security, if any: what the Reviews page's Tool modules tab lists.
    pending_review: PendingReview | None = None
    # How many distinct secrets the module's operations read that the tenant has not set.
    unset_secrets: int = 0
    # Null on a module no template made.
    template_id: str | None = None
    protection: Literal["system", "managed"] | None = None


class SecretNeed(Out):
    """A `{{NAME}}` an operation's headers or path read, and whether the tenant has set it."""

    name: str
    set: bool
    # Set, and readable by this module's team (a secret limited to other teams is refused at call time).
    available: bool = True


class OperationHeader(Out):
    key: str
    value: str


class CodeLimits(Out):
    memory_mb: int
    time_s: float
    calls: int


class CodeSettings(Out):
    """A code operation's function: what runs, the tools it may call and the secrets it may hand them."""

    source: str
    entry: str
    bindings: list[str]
    secrets: list[str]
    limits: CodeLimits


class ModuleOperation(Out):
    id: str
    tool_id: str
    name: str
    description: str
    access: Access
    enabled: bool
    # How the gateway runs it; only `http` operations have a call shape a builder edits.
    executor: Literal["http", "mcp", "stub", "local", "code", "plugin"]
    method: Method | None = None
    path: str | None = None
    # Literals or {{NAME}} secret references; a literal credential is refused on save, so no value here is secret.
    headers: list[OperationHeader] = Field(default_factory=list[OperationHeader])
    # The sign-in header (Authorization, X-Api-Key, Cookie) a tool saved before they were refused still sends:
    # its page says to move the key to the app. Null when it sends none.
    sign_in_header: str | None = None
    body: str | None = None
    body_encoding: BodyEncoding | None = None
    response_transform: str | None = None
    timeout_ms: int | None = None
    input: list[SchemaField]
    masked_output: list[str]
    binding: SubjectBinding | None
    rate_limit_per_min: int
    requires_approval: bool
    amount_max: float | None = None
    # The write approval policy: distinct approvers (1 or 2) and the team they come from. Whether the person who asked
    # may approve is the tenant's requesterMayDecide policy, not a per-operation setting.
    approvers: int
    # None on a plugin's module, which no team owns: the run's own team approves.
    approver_team: str | None
    # Approving asks the approver for a step-up: set here, or implied by two approvers.
    step_up: bool
    idempotent: bool
    # Only a person's own sign-in signs its calls: never the team backup.
    needs_person: bool = False
    # The scopes a person's own sign-in must hold to call it; one lacking any is asked to connect again.
    scopes: list[str] = Field(default_factory=list)
    calls24h: int = Field(alias="calls24h")
    error_rate: float
    p95_ms: int = Field(alias="p95Ms")
    approved_workflows: int
    secrets: list[SecretNeed] = Field(default_factory=list[SecretNeed])
    # The mock response: answers a stub executor and every test against the mock.
    stub: Any = None
    # Set for a code operation only.
    code: CodeSettings | None = None


class ModuleApproval(Out):
    id: str
    workflow_id: str
    workflow_name: str
    environment: Environment
    major: int
    operations: list[str]
    constraints: str | None = None
    requested_by: str
    justification: str
    requested_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    status: Literal["requested", "approved", "rejected", "expired", "revoked"]
    expires_at: str | None = None
    reason: str | None = None
    # The Human Tasks review deciding the request and the team whose reviewers decide it; absent on requests
    # made before they went to Reviews.
    review_id: str | None = None
    decider_team: str | None = None


class ToolGrant(ModuleApproval):
    """A workflow's access to one module, as the Access tab lists it across modules."""

    module_id: str
    module_name: str


class ToolGrantList(ListResult[ToolGrant]):
    """GET /v1/tool-modules/grants: one page, with `facets.view` counting active, expiring, requested, expired, ended
    and all."""


class Reachability(Out):
    environment: Environment
    ok: bool
    checked_at: str


class ModuleVersion(Out):
    version: str
    major: int
    status: Literal["draft", "in_review", "published", "deprecated", "revoked"]
    published_at: str | None = None
    published_by: str
    note: str
    changes: list[OperationChange]
    pinned_by: list[ModuleRef]
    reachability: list[Reachability]
    # Its review in agents-service's Reviews: the request id, when it was asked for, who decided, and the
    # reason given for a no.
    review_id: str | None = None
    requested_at: str | None = None
    reviewer: str | None = None
    finding: str | None = None
    # Whether the publish waited for a review, and the publish-review mode it followed.
    review_required: bool | None = None
    policy: Literal["always", "major", "never"] | None = None


class RunContextOption(Out):
    id: str
    label: str
    workflow_id: str
    workflow_name: str
    case_id: str
    bindings: dict[str, str]


class ModuleAuth(Out):
    # The connection's kind (auth/kinds.py), or none.
    kind: str
    header: str | None = None
    # A client certificate is sent, whatever the kind.
    certificate: bool | None = None


class ToolModuleDetail(ToolModule):
    owner_contacts: list[str]
    auth: ModuleAuth
    timeout_ms: int
    egress_hosts: list[str]
    data_classification: Literal["public", "internal", "confidential", "restricted"]
    operations: list[ModuleOperation]
    pending_changes: list[OperationChange]
    approvals: list[ModuleApproval]
    versions: list[ModuleVersion]
    run_contexts: list[RunContextOption]
    # What the caller may do with it; absent on a response to a service.
    can_edit: bool | None = None
    can_delete: bool | None = None
    can_publish: bool | None = None


class ModuleStats(Out):
    modules: int
    operations: int
    calls24h: int = Field(alias="calls24h")
    error_rate: float
    expiring_approvals: int
    expiring_modules: int


class ModuleViewCounts(Out):
    all: int
    needs_approval: int = Field(alias="needs_approval")
    expiring: int
    expired: int
    failing: int
    security_review: int = Field(alias="security_review")


class ModuleList(ListResult[ToolModule]):
    stats: ModuleStats
    view_counts: ModuleViewCounts


class ActivityDay(Out):
    date: str
    count: int
    errors: int
    p95_ms: int = Field(alias="p95Ms")


class ModuleActivity(Out):
    days: list[ActivityDay]
    denied24h: int = Field(alias="denied24h")
    recent: list[ToolCallRow]


class BoundInput(Out):
    arg: str
    value: str
    source: BindingSource


class InvalidField(Out):
    field: str
    message: str


class HeaderOut(Out):
    key: str
    value: str


class TestRequestOut(Out):
    method: str
    url: str
    headers: list[HeaderOut]
    body: str | None = None


class TestLogLine(Out):
    at_ms: float
    message: str


class ModuleTestResult(Out):
    decision: Literal["allow", "deny", "invalid"]
    deny_reason: str | None = None
    deny_message: str | None = None
    invalid: list[InvalidField] | None = None
    test_approval_token: str | None = None
    status: int
    latency_ms: int
    bound: list[BoundInput]
    would_pause: bool
    output: Any
    masked: list[str]
    call_id: str
    # Sandbox target: whether the answer came from the stub (a write) or the real system (a read), and which host.
    stubbed: bool | None = None
    # The mock answer it came from, when the test environment holds one for this input.
    mock_id: str | None = None
    reached_host: str | None = None
    # What was sent (secret values masked), the answer before the transform, why the transform failed, and the
    # gateway's steps in order.
    request: TestRequestOut | None = None
    raw_response: Any = None
    transform_error: str | None = None
    log: list[TestLogLine] = Field(default_factory=list[TestLogLine])


class Skipped(Out):
    id: str
    reason: str


class BulkResult(Out):
    updated: list[str]
    skipped: list[Skipped]


# Requests


class SchemaFieldIn(In):
    name: str
    type: FieldType
    required: bool
    description: str | None = None
    format: str | None = None
    enum: list[str] | None = None
    example: str | None = None
    default: str | int | float | bool | None = None


class SubjectBindingIn(In):
    arg: str
    bind_to: BindingSource
    mode: Literal["equals", "within"]
    required: bool


class DiscoveredOperationIn(In):
    name: str
    description: str
    access: Access
    method: Method | None = None
    path: str | None = None
    group: str
    input: list[SchemaFieldIn]


class HeaderIn(In):
    key: str
    value: str


class HttpOperationIn(In):
    name: str
    description: str
    access: Access
    method: Method
    url: str
    headers: list[HeaderIn] = Field(default_factory=list[HeaderIn])
    body: str | None = None
    body_encoding: BodyEncoding | None = None


SECRET_NAME = r"^[A-Z][A-Z0-9_]*$"


class CodeLimitsIn(In):
    """What a run may use; runner-service holds each to the deployment's cap whatever is asked."""

    memory_mb: int = Field(default=256, ge=32, le=4096)
    time_s: float = Field(default=10, gt=0, le=600)
    calls: int = Field(default=20, ge=0, le=1000)


class CodeSettingsIn(In):
    source: str = Field(min_length=1, max_length=100_000)
    entry: str = Field(default="main", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    # Tool names the function may call with ops.call, each decided as the caller's own call.
    bindings: list[str] = Field(default_factory=list[str], max_length=50)
    # Secret names the function may hand to a bound read with ops.secret; their values never reach the function.
    secrets: list[Annotated[str, Field(pattern=SECRET_NAME)]] = Field(default_factory=list[str], max_length=20)
    limits: CodeLimitsIn = Field(default_factory=CodeLimitsIn)


class CodeOperationIn(In):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    access: Access = "read"
    input: list[SchemaFieldIn] = Field(default_factory=list[SchemaFieldIn])
    code: CodeSettingsIn


class ModuleIn(In):
    name: str
    display_name: str
    system: str = ""
    # Optional: the kind follows its operations (http, a source's kind, or code for a function).
    type: ModuleType | None = None
    # The system's base address, for a module with no connection. A module on a connection calls its connection's
    # base address, so a hand-built operation names a path and an endpoint beside the connection is refused.
    endpoint: str = ""
    # Optional: the app the module's calls sign in through; none means auth kind "none".
    connection_id: str | None = None
    sign_in: ModuleSignInIn = "person_or_team"
    operations: list[DiscoveredOperationIn] | None = None
    # Where `operations` were discovered. Given, the service re-reads it and takes each operation's method, path,
    # inputs and headers from there; the caller's copies only pick operations and confirm reads.
    source: ModuleSourceIn | None = None
    http: HttpOperationIn | None = None
    # A code module's first function.
    function: CodeOperationIn | None = None
    unique_name: bool = False
    # Set only by the provisioner: the template slot this record fills and what a person may change of it.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class BlankModuleIn(In):
    display_name: str
    name: str
    # Optional: the kind follows the operations added; http until then.
    type: ModuleType | None = None
    description: str | None = None
    # The app whose base address and sign-in its tools use.
    connection_id: str | None = None
    # Set only by the provisioner: the template slot this record fills and what a person may change of it.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class ModuleDetailsPatchIn(In):
    display_name: str | None = None
    description: str | None = None
    sign_in: ModuleSignInIn | None = None
    # Set only by the provisioner: the template slot this record fills and what a person may change of it.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class ConnectionIn(In):
    connection_id: str | None


class IdsIn(In):
    ids: list[str]


class OperationPatchIn(In):
    """A field left out is unchanged; `binding: null` removes the binding. The call shape (method, path, headers,
    body, transform, timeout) applies to http operations only; `responseTransform: null` or `timeoutMs: null` clears
    it, back to no transform and the module timeout."""

    method: Method | None = None
    path: str | None = None
    headers: list[HeaderIn] | None = None
    body: str | None = None
    body_encoding: BodyEncoding | None = None
    response_transform: str | None = None
    timeout_ms: int | None = None
    enabled: bool | None = None
    requires_approval: bool | None = None
    rate_limit_per_min: int | None = None
    binding: SubjectBindingIn | None = None
    amount_max: float | None = None
    description: str | None = None
    approvers: int | None = None
    approver_team: str | None = None
    step_up: bool | None = None
    needs_person: bool | None = None
    # Each scope as the system names it, no spaces; [] asks for none beyond the connection's.
    scopes: Annotated[list[Annotated[str, Field(pattern=r"^\S{1,200}$")]], Field(max_length=50)] | None = None
    access: Access | None = None
    # The whole input schema as it should be; fields left out of the list are removed.
    input: list[SchemaFieldIn] | None = None
    # The mock response: what the stub executor and every test write answer; null is back to {"ok": true}.
    stub: Any = None
    # A code operation's function, bindings, secrets and limits as they should be.
    code: CodeSettingsIn | None = None


class NoteIn(In):
    note: str


class ApprovalRequestIn(In):
    workflow_id: str
    environment: Environment
    operations: list[str]
    expires_in_days: int
    justification: str


class DecisionIn(In):
    decision: Literal["approved", "rejected"]
    reason: str | None = None


class RevokeIn(In):
    ids: list[str]
    reason: str


class TestDraftIn(In):
    """The workbench's unsaved transform and mock, tried by one test without staging them. A key left out
    uses the operation's own; `responseTransform: null` runs with no transform."""

    response_transform: str | None = None
    stub: Any = None


class ModuleTestIn(In):
    operation: str
    context_id: str
    target: Literal["stub", "sandbox"]
    input: dict[str, Any]
    simulate_approval: bool = False
    draft: TestDraftIn | None = None
    # Values for this one call, by secret name; never stored, logged or returned.
    secret_values: dict[str, str] | None = None
    # Which of the connection's environments a Real run uses; test unless the person picks production.
    environment: ConnectionEnvironment = "test"


class ToolRunIn(In):
    """One run of one tool from its page: Mock answers from its mock and reaches nothing, Real is the gateway
    call, with every check, in the environment picked."""

    mode: Literal["mock", "real"]
    input: dict[str, Any] = Field(default_factory=dict[str, Any])
    environment: ConnectionEnvironment = "test"


class ToolRunResult(ModuleTestResult):
    # True when the answer came from a mock, never the system: every Mock run, and a Real one the test environment's
    # mock answers for this input.
    mocked: bool


# Executions


class CallIdentity(Out):
    kind: str
    id: str
    name: str


class CallApproval(Out):
    kind: Literal["person", "policy", "none"]
    token_id: str | None = None
    # The people the approval token names (executions.call_row).
    by: str | None = None


class CallRunAs(Out):
    """Whom a call ran as: a person (by the email their acting-for token named) or the team account."""

    kind: Literal["person", "team"]
    email: str | None = None


class ToolCallRow(Out):
    """One gateway call as the console's ToolCallRow, with the identity fields the executions log fills."""

    id: str
    at: str
    gateway: Literal["data", "ai"]
    workflow_id: str
    workflow_name: str
    agent_slug: str
    agent_name: str
    run_id: str
    case_id: str | None = None
    target: str
    system: str
    # The tool's display name and its app's: what a chat, an approval and the log show in place of `target`.
    title: str | None = None
    app: str | None = None
    operation: Literal["read", "write", "completion"]
    record: str | None = None
    approval: CallApproval
    status: Literal["ok", "error", "denied", "awaiting_approval", "replayed", "running"]
    latency_ms: int
    subject: CallIdentity | None = None
    actor: CallIdentity | None = None
    step: str | None = None
    deployment_id: str | None = None
    approval_token_id: str | None = None
    decision: Literal["allow", "deny"] | None = None
    deny_reason: str | None = None
    # A failed call: the executor's code, its message, and the side it broke on.
    error_code: str | None = None
    error_message: str | None = None
    failure_side: Literal["ours", "upstream"] | None = None
    # The call a replayed write repeated: it ran nothing and returned that call's result.
    replay_of: str | None = None
    # The log's outcome as recorded (ok, replayed, error, refused, in_progress, running); `status` maps it for display.
    outcome: str | None = None
    # The row whose call carries the write's side effect (the claim), as opposed to a refusal or a replay of it.
    effect: bool = False
    # The environment the call used and the connection that signed it in; absent on older rows.
    environment: ConnectionEnvironment | None = None
    connection_id: str | None = None
    # Where the call came in: POST /v1/calls or the MCP server, and the assistant that sent an MCP call.
    channel: Literal["api", "mcp", "console"] | None = None
    client_name: str | None = None
    acting_for: str | None = None
    credential: Literal["person", "team"] | None = None
    run_as: CallRunAs | None = None


class ExecutionList(ListResult[ToolCallRow]):
    pass


# Discovery and import


class DiscoveredOperation(Out):
    name: str
    description: str
    access: Access
    method: Method | None = None
    path: str | None = None
    group: str
    input: list[SchemaField]


class DiscoveryResult(Out):
    type: ModuleType
    system: str
    suggested_name: str
    version: str
    endpoint: str
    operations: list[DiscoveredOperation]
    warnings: list[str]
    # No operation carries an auth header: imported as is, calls go out with no credentials.
    no_auth: bool = False


class ModuleSourceIn(In):
    """`{kind: 'mcp', url}` or `{kind: 'openapi', specUrl | fileName | fileId}`, each with an optional connection."""

    kind: Literal["mcp", "openapi"]
    url: str | None = None
    spec_url: str | None = None
    file_name: str | None = None
    file_id: str | None = None
    connection_id: str | None = None


class ImportOperationsIn(In):
    source: ModuleSourceIn
    operations: list[DiscoveredOperationIn]


class ReviewDecisionIn(In):
    """A decision made in Reviews, sent by agents-service."""

    request_id: str
    version: str
    decision: Literal["approved", "rejected", "returned"]
    reason: str | None = None
    by: str | None = None
