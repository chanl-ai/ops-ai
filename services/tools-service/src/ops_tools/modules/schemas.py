"""Wire models for `/v1/tool-modules`, mirroring apps/console/src/lib/types/tool-modules.ts field for field.

Responses are built as dicts and returned through `ok()`; these models document them in openapi.json, and the tests'
contract checker validates every response against that document, so a field added on one side fails a test."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_service_kit.http import ListResult, Out

Access = Literal["read", "write", "money_movement"]
ModuleType = Literal["mcp", "openapi", "http", "code"]
Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
Environment = Literal["dev", "test", "production"]
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
    updated_at: str
    # The review waiting on Security, if any: what the Reviews page's Tool modules tab lists.
    pending_review: PendingReview | None = None


class OperationHeader(Out):
    key: str
    value: str


class ModuleOperation(Out):
    id: str
    tool_id: str
    name: str
    description: str
    access: Access
    enabled: bool
    # How the gateway runs it; only `http` operations have a call shape a builder edits.
    executor: Literal["http", "mcp", "stub", "local"]
    method: Method | None = None
    path: str | None = None
    # Literals or {{NAME}} secret references; a literal credential is refused on save, so no value here is secret.
    headers: list[OperationHeader] = Field(default_factory=list[OperationHeader])
    body: str | None = None
    response_transform: str | None = None
    timeout_ms: int | None = None
    input: list[SchemaField]
    masked_output: list[str]
    binding: SubjectBinding | None
    rate_limit_per_min: int
    requires_approval: bool
    four_eyes: bool
    amount_max: float | None = None
    idempotent: bool
    calls24h: int = Field(alias="calls24h")
    error_rate: float
    p95_ms: int = Field(alias="p95Ms")
    approved_workflows: int


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


class SecurityReview(Out):
    id: str
    major: int
    version: str
    decision: Literal["pending", "approved", "changes_requested"]
    requested_by: str
    requested_at: str
    reviewer: str | None = None
    decided_at: str | None = None
    findings: list[str]
    note: str | None = None


class RunContextOption(Out):
    id: str
    label: str
    workflow_id: str
    workflow_name: str
    case_id: str
    bindings: dict[str, str]


class ModuleAuth(Out):
    kind: Literal["oauth_client_credentials", "mtls", "api_key", "basic", "none"]
    header: str | None = None


class ToolModuleDetail(ToolModule):
    owner_contacts: list[str]
    auth: ModuleAuth
    timeout_ms: int
    egress_hosts: list[str]
    data_classification: Literal["public", "internal", "confidential", "restricted"]
    operations: list[ModuleOperation]
    pending_changes: list[OperationChange]
    approvals: list[ModuleApproval]
    reviews: list[SecurityReview]
    versions: list[ModuleVersion]
    run_contexts: list[RunContextOption]


class ModuleStats(Out):
    modules: int
    operations: int
    calls24h: int = Field(alias="calls24h")
    error_rate: float
    money_operations: int
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
    reached_host: str | None = None


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


class ModuleIn(In):
    name: str
    display_name: str
    system: str
    type: ModuleType
    endpoint: str
    connection_id: str
    operations: list[DiscoveredOperationIn] | None = None
    # Where `operations` were discovered. Given, the service re-reads it and takes each operation's method, path,
    # inputs and headers from there; the caller's copies only pick operations and confirm reads.
    source: ModuleSourceIn | None = None
    http: HttpOperationIn | None = None
    unique_name: bool = False


class BlankModuleIn(In):
    display_name: str
    name: str
    type: ModuleType
    description: str | None = None


class ModuleDetailsPatchIn(In):
    display_name: str | None = None
    description: str | None = None


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
    response_transform: str | None = None
    timeout_ms: int | None = None
    enabled: bool | None = None
    requires_approval: bool | None = None
    rate_limit_per_min: int | None = None
    binding: SubjectBindingIn | None = None
    amount_max: float | None = None
    description: str | None = None


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


class ModuleTestIn(In):
    operation: str
    context_id: str
    target: Literal["stub", "sandbox"]
    input: dict[str, Any]
    simulate_approval: bool = False


# Executions


class CallIdentity(Out):
    kind: str
    id: str
    name: str


class CallApproval(Out):
    kind: Literal["person", "policy", "none"]
    token_id: str | None = None


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
    operation: Literal["read", "write", "money_movement", "completion"]
    record: str | None = None
    approval: CallApproval
    status: Literal["ok", "error", "denied", "awaiting_approval"]
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
    decision: Literal["approved", "changes_requested"]
    findings: list[str] = Field(default_factory=list[str])
    note: str | None = None
