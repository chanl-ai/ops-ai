"""The tool-module registry: modules, their operations, versions, security reviews and workflow approvals.

A module and its children are one aggregate. The service reads it whole, changes it, and writes it back whole with
`put`, which replaces the children in the same transaction and lands only while the module's `revision` still equals
the one read, so two concurrent edits cannot silently overwrite each other.

Every table carries `tenant_id`; `tool_modules` also carries `team_id`, the team that owns the module. The database
holds every table to its tenant (tools_0080, tools_0086). The team is held in code (`team_modules`, `granted`): a
module with no team is read by every team, a module granted to another team's workflow is read by that team, and a
call resolves its module across teams, so a team policy would hide rows these reads need.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar, Literal, NotRequired, TypedDict

import sqlalchemy as sa
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.schema import SchemaItem

from ops_service_kit.ids import new_id
from ops_service_kit.listing import ListParams
from ops_store import Guarantee, isolation
from ops_store.listing import LISTED, ListPage, list_page
from ops_store.outbox import (
    DESCRIPTION_MAX,
    Event,
    TemplateKind,
    ToolChanged,
    ToolModule,
    ToolOperation,
    ToolPublished,
    ToolTeamStateChanged,
    outbox_table,
)
from ops_store.outbox import add as add_event
from ops_store.schema import TENANT_SCOPED
from ops_store.store import Store
from ops_store.team_scope import acting_as, acting_team, any_team, team_visible

from .tenancy import ROLE, SYSTEM_ROLE

metadata = sa.MetaData()

_TS = sa.DateTime(timezone=True)

tool_modules = sa.Table(
    "tool_modules",
    metadata,
    # Ids are unique within a tenant only: every tenant's dev seed uses the console's ids (mod_core_banking).
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    # Null for a workspace-level module every team reads and calls (the platform tools).
    sa.Column("team_id", sa.String(64)),
    sa.Column("name", sa.String(120), nullable=False, info=LISTED),
    sa.Column("display_name", sa.String(200), nullable=False, info=LISTED),
    sa.Column("system", sa.String(200), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("owner_team", sa.String(120), nullable=False, info=LISTED),
    sa.Column("owner_contacts", sa.JSON, nullable=False),
    sa.Column("auth", sa.JSON, nullable=False),
    sa.Column("timeout_ms", sa.Integer, nullable=False),
    sa.Column("data_classification", sa.String(16), nullable=False),
    sa.Column("catalog_id", sa.String(64)),
    sa.Column("connection_id", sa.String(64)),
    # Whose account the module's calls may sign in with: team, person or either; a connection whose sign-in
    # does not fit is refused when it is chosen.
    sa.Column("sign_in", sa.String(16), nullable=False, server_default="person_or_team"),
    # The template slot a provisioned record fills, found again by it on the next run, and what a person may change:
    # `system` nothing, `managed` anything. Null on a record no template made.
    sa.Column("template_id", sa.String(120), index=True, info=LISTED),
    sa.Column("protection", sa.String(16)),
    sa.Column("reachable", sa.Boolean, nullable=False),
    sa.Column("drift", sa.Boolean, nullable=False),
    sa.Column("version", sa.String(32), nullable=False),
    # Staged operation changes not yet published, and the operations as they were before the first one (discard).
    sa.Column("pending", sa.JSON, nullable=False),
    sa.Column("baseline", sa.JSON),
    # Rises on every write of the aggregate; `put` lands only against the revision it read (CAS). 0 marks a module
    # as the dev seed wrote it and nobody has changed since, which the seed may refresh.
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("updated_at", _TS, nullable=False, info=LISTED),
    # Workflows pin a module by name, so a name is unique within a team. A workspace-level
    # module (null team) is unique on (tenant, name) so two shared copies cannot land.
    info=TENANT_SCOPED,
)

_OWNED = tool_modules.c.team_id.isnot(None)
_SHARED = tool_modules.c.team_id.is_(None)
# The Tools list sorts by these (store/module_list.py) across the tenant's teams; each leads its index.
sa.Index("ix_tool_modules_display_name", tool_modules.c.display_name)
sa.Index("ix_tool_modules_owner_team", tool_modules.c.owner_team)
sa.Index("ix_tool_modules_updated_at", tool_modules.c.updated_at)
sa.Index("ix_tool_modules_list_name", tool_modules.c.name)
sa.Index(
    "ux_tool_modules_name",
    tool_modules.c.tenant_id,
    tool_modules.c.team_id,
    tool_modules.c.name,
    unique=True,
    postgresql_where=_OWNED,
    mssql_where=_OWNED,
    sqlite_where=_OWNED,
)
sa.Index(
    "ux_tool_modules_shared_name",
    tool_modules.c.tenant_id,
    tool_modules.c.name,
    unique=True,
    postgresql_where=_SHARED,
    mssql_where=_SHARED,
    sqlite_where=_SHARED,
)


def _child(name: str, *columns: SchemaItem, **kw: Any) -> sa.Table:
    return sa.Table(
        name,
        metadata,
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("module_id", sa.String(64), nullable=False),
        # Order within the module, as the console lists them.
        sa.Column("position", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "module_id"], ["tool_modules.tenant_id", "tool_modules.id"], ondelete="CASCADE"
        ),
        sa.Index(f"ix_{name}_module", "tenant_id", "module_id"),
        *columns,
        # Held to its tenant by the database (tools_0080); read through its module, whose team the query names.
        info=TENANT_SCOPED,
        **kw,
    )


module_operations = _child(
    "module_operations",
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("tool_id", sa.String(64), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    # The access class the gateway enforces; set here by the owner, never by the caller (read or write).
    sa.Column("access", sa.String(16), nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False),
    # How the gateway runs it: `http` calls the module's endpoint, `stub` answers with `stub` (a seeded system with no
    # reachable upstream), `local` runs the Runtime's demo tool of the same name, `code` runs the operation's function
    # on runner-service.
    sa.Column("executor", sa.String(8), nullable=False, server_default="http"),
    sa.Column("method", sa.String(8)),
    sa.Column("path", sa.Text),
    # Header values are literals or {{NAME}} references to a secret; a literal credential is refused on save.
    sa.Column("headers", sa.JSON, nullable=False, server_default="[]"),
    # A JSON body template with {{arg}} placeholders; without one the arguments the URL did not use are the body.
    sa.Column("body", sa.Text),
    # How `body` is sent: json (null, as before), form (a JSON object of field to template, form-encoded) or raw
    # (the template as text, with the Content-Type header the operation sets).
    sa.Column("body_encoding", sa.String(8)),
    # A Jinja2 template over the parsed response (ops_tools.transform); null returns the response as it came.
    sa.Column("response_transform", sa.Text),
    # This operation's limit; null uses the module's timeout_ms.
    sa.Column("timeout_ms", sa.Integer),
    sa.Column("input", sa.JSON, nullable=False),
    sa.Column("masked_output", sa.JSON, nullable=False),
    sa.Column("binding", sa.JSON),
    sa.Column("rate_limit_per_min", sa.Integer, nullable=False),
    sa.Column("requires_approval", sa.Boolean, nullable=True),
    # The tool's own answer to who approves a call (none, person or reviewer); null follows its app, then the team.
    # `reviewer_role` is the role that decides when the answer is a reviewer. Loosening either is a reviewed change.
    sa.Column("approval_mode", sa.String(8), nullable=True),
    sa.Column("reviewer_role", sa.String(64), nullable=True),
    sa.Column("amount_max", sa.Numeric(14, 2)),
    # The write approval policy (docs/architecture/tool-lifecycle.md): how many distinct people approve a call, the
    # team they come from (None: the module's owning team), and whether the person who asked may be one of them.
    sa.Column("approvers", sa.Integer, nullable=False, server_default="1"),
    sa.Column("approver_team", sa.String(64)),
    # Approving asks the approver to re-authenticate even with one approver: a hold on a customer's funds.
    sa.Column("step_up", sa.Boolean, nullable=False, server_default=sa.false()),
    # Only a person's own sign-in may sign this operation's calls: a call with nobody behind it is refused
    # even where the connection's team backup is on.
    sa.Column("needs_person", sa.Boolean, nullable=False, server_default=sa.false()),
    # The scopes a person's own sign-in must hold to call it; one lacking any is asked to sign in again with
    # them. Not reviewed: asking for a scope grants nothing, the system decides what a token may do.
    sa.Column("scopes", sa.JSON, nullable=False, server_default="[]"),
    # The result shape the operation declares (`x-ops-shape`: rows, series, record or metric), for the chat's shaper.
    sa.Column("output_shape", sa.String(16)),
    # The JSON Schema of the first success response, as an imported OpenAPI document gives it: a workflow
    # step's output fields before it runs. Null when the import had none.
    sa.Column("response_schema", sa.JSON),
    # A code operation's function: source, entry, the tool names it may call, the secret names it may hand to
    # them, and its limits. Null for every other executor.
    sa.Column("code", sa.JSON),
    # Read or write only (migration tools_0012): a database holding any other class is rebuilt, never read.
    sa.CheckConstraint("access IN ('read', 'write')", name="ck_module_operations_access"),
    # The gateway resolves a call by tool name in the run's team, so the same name may exist in
    # another team's module. Unique per module: two operations of one module cannot share it.
    sa.UniqueConstraint("tenant_id", "module_id", "name", name="ux_module_operations_name"),
)

operation_mocks = sa.Table(
    "operation_mocks",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("module_id", sa.String(64), nullable=False),
    sa.Column("operation", sa.String(120), nullable=False),
    # test: answers test-environment calls; example: the operation's example answer (EXAMPLE). Production never reads
    # a mock.
    sa.Column("environment", sa.String(16), nullable=False),
    # Order within the operation's mocks: the first whose match holds answers.
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("name", sa.String(200), nullable=False, info=LISTED),
    # Input field to the value it must equal; empty matches every call.
    sa.Column("match", sa.JSON, nullable=False),
    sa.Column("status", sa.Integer, nullable=False),
    sa.Column("body", sa.JSON),
    sa.Column("headers", sa.JSON, nullable=False),
    sa.Column("delay_ms", sa.Integer, nullable=False),
    # Answers nothing within the operation's time limit: the call fails UPSTREAM_TIMEOUT as a real one would.
    sa.Column("timeout", sa.Boolean, nullable=False),
    # The one a call gets when no other matches; at most one per operation and environment, kept by the service.
    sa.Column("is_default", sa.Boolean, nullable=False),
    # The logged call it was saved from, when it was.
    sa.Column("from_call_id", sa.String(64)),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("updated_at", _TS, nullable=False),
    sa.Index("ix_operation_mocks_operation", "tenant_id", "operation", "environment", "position"),
    # An operation's mocks sort by name.
    sa.Index("ix_operation_mocks_name", "tenant_id", "name"),
    info=TENANT_SCOPED,
)

# The mock "environment" holding an operation's example answer: what Mock answers when no test mock matches,
# what a system with no upstream answers in every environment, and what an output schema is inferred from. Apart from
# "test" on purpose: a test mock intercepts test-environment calls, and an example must not keep a Real run in test from
# reaching the system.
EXAMPLE = "example"
# An operation with no example answers this: what an import writes when the document gives none (registry._output).
NO_EXAMPLE: dict[str, JsonValue] = {"ok": True}
# Who an example written through an operation is recorded as made by; migration tools_0052 uses the same name.
EXAMPLE_AUTHOR = "operation example"

module_versions = _child(
    "module_versions",
    sa.Column("version", sa.String(32), nullable=False),
    sa.Column("major", sa.Integer, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("published_at", _TS),
    sa.Column("published_by", sa.String(200), nullable=False),
    sa.Column("note", sa.Text, nullable=False),
    sa.Column("changes", sa.JSON, nullable=False),
    sa.Column("pinned_by", sa.JSON, nullable=False),
    sa.Column("reachability", sa.JSON, nullable=False),
    # The version's review, a publish request in agents-service's Reviews: its id, when it was asked for, and
    # once decided who decided and, for a no, the reason, which the module shows as the finding.
    sa.Column("review_id", sa.String(64)),
    sa.Column("requested_at", _TS),
    sa.Column("reviewer", sa.String(200)),
    sa.Column("finding", sa.Text),
    # Whether the publish waited for a review, and the team's publish-review mode it followed; null on a
    # version published before the mode was read.
    sa.Column("review_required", sa.Boolean),
    sa.Column("policy", sa.String(16)),
    sa.UniqueConstraint("tenant_id", "module_id", "version", name="ux_module_versions_version"),
)

module_approvals = _child(
    "module_approvals",
    sa.Column("workflow_id", sa.String(64), nullable=False),
    sa.Column("workflow_name", sa.String(200), nullable=False, info=LISTED),
    # The team owning the workflow when the approval was requested, from agents-service: who may see the
    # module through this approval. Null on approvals made before workflows came from agents-service.
    sa.Column("workflow_team_id", sa.String(64)),
    sa.Column("environment", sa.String(16), nullable=False),
    sa.Column("major", sa.Integer, nullable=False),
    sa.Column("operations", sa.JSON, nullable=False),
    sa.Column("constraints", sa.Text),
    sa.Column("requested_by", sa.String(200), nullable=False),
    # The requester as the token names them: the requester rule compares it, never the display name above.
    # Null on approvals made before it was kept, which then match nobody.
    sa.Column("requested_by_email", sa.String(320)),
    sa.Column("justification", sa.Text, nullable=False),
    sa.Column("requested_at", _TS, nullable=False, info=LISTED),
    sa.Column("decided_by", sa.String(200)),
    sa.Column("decided_at", _TS),
    # requested, approved, rejected or revoked; `expired` is computed from expires_at and never stored.
    sa.Column("status", sa.String(16), nullable=False, info=LISTED),
    sa.Column("expires_at", _TS),
    sa.Column("reason", sa.Text),
    # The team whose reviewers decide the request and the Human Tasks review deciding it; null on approvals
    # made before requests went to Reviews.
    sa.Column("decider_team", sa.String(64)),
    sa.Column("review_id", sa.String(64)),
    # The tool access list sorts by workflow, status and request time.
    sa.Index("ix_module_approvals_workflow_name", "tenant_id", "workflow_name"),
    sa.Index("ix_module_approvals_status", "tenant_id", "status"),
    sa.Index("ix_module_approvals_requested_at", "tenant_id", "requested_at"),
)

# The hosts a module calls: entries of the tenant's egress allow-list (`store.egress`), never a list of its own. The
# foreign key refuses a host the list does not hold; a listed host a module uses cannot be removed (RESTRICT).
module_egress_hosts = sa.Table(
    "module_egress_hosts",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("module_id", sa.String(64), primary_key=True),
    sa.Column("host", sa.String(253), primary_key=True),
    sa.Column("position", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(
        ["tenant_id", "module_id"], ["tool_modules.tenant_id", "tool_modules.id"], ondelete="CASCADE"
    ),
    sa.ForeignKeyConstraint(
        ["tenant_id", "host"], ["egress_hosts.tenant_id", "egress_hosts.host"], ondelete="RESTRICT"
    ),
    # Removing a listed host looks up the modules that use it.
    sa.Index("ix_module_egress_hosts_host", "tenant_id", "host"),
    info=TENANT_SCOPED,
)

# The fields of an operation that say how it is called; a staged change to any of them waits for publish.
CALL_SHAPE = ("method", "path", "headers", "body", "body_encoding", "response_transform", "timeout_ms")
# The write approval policy, which a staged edit must not loosen before Security reviews it either.
APPROVAL_POLICY = ("approvers", "approver_team", "step_up")
# Every field of an operation whose edit can be major, so Security reviews it: where and how it is called, what it may
# be sent, whether it is exposed, and how a write to it is approved and limited. Calls see these from the published
# operations while edits are staged (operation_named), and publish compares them with the published ones to decide
# major; one list, so the two cannot drift. Headers, transform and timeout are minor.
REVIEWED = (
    "method",
    "path",
    "body",
    "body_encoding",
    "input",
    "access",
    "requires_approval",
    "approval_mode",
    "reviewer_role",
    "enabled",
    "binding",
    "amount_max",
    "needs_person",
    *APPROVAL_POLICY,
)


# The shapes below are a module and its children as stored. A row is checked against them as it leaves the store
# (MODULE_COLUMNS, OPERATION and the other adapters), which keeps only the keys they name: each names every column and
# every key the request models (modules/schemas.py) let a writer store, so a save writes back what it read.
class InputField(TypedDict):
    """One argument of an operation. A field saved through the request model names every key, unset ones as null."""

    name: str
    type: str
    required: bool
    description: NotRequired[str | None]
    format: NotRequired[str | None]
    # In the order the request model writes them: a read writes a field back with the keys in this order.
    enum: NotRequired[list[str] | None]
    example: NotRequired[JsonValue]
    default: NotRequired[JsonValue]


class Header(TypedDict):
    """A header an operation sends: a literal or a {{NAME}} reference to a secret."""

    key: str
    value: str


class Binding(TypedDict):
    """An input the caller's context fills, which the call may not override."""

    arg: str
    bindTo: str
    mode: str
    required: bool


class CodeLimits(TypedDict):
    memoryMb: int
    timeS: int | float
    calls: int


class CodeSettings(TypedDict):
    """A code operation's function: source, entry, the tools it may call, the secrets it may hand them, its limits."""

    source: str
    entry: str
    bindings: list[str]
    secrets: list[str]
    limits: CodeLimits


class Change(TypedDict):
    """One reviewed edit of a module, waiting for publish or recorded on a version."""

    operation: str
    kind: str
    detail: str
    major: bool


class Reachability(TypedDict):
    environment: str
    ok: bool
    checkedAt: str


class IdentityRow(TypedDict):
    """One thing that tells an account apart from the app's others (the keys of `IdentityEntry`)."""

    label: str
    value: str
    shown: str


class AccountOption(TypedDict):
    """One account of an app a person holds, as its sign-in named them."""

    connectionId: str
    name: str
    account: str | None
    identity: list[IdentityRow]


class AccountChoice(TypedDict):
    """What a call asks a person who holds two or more accounts of an app and chose no default."""

    app: str
    appId: str
    accounts: list[AccountOption]


class OperationDefaults(TypedDict):
    """The columns a built operation may leave to their defaults; `operation_defaults` fills them."""

    body_encoding: str | None
    response_transform: str | None
    timeout_ms: int | None
    approval_mode: str | None
    reviewer_role: str | None
    approvers: int
    approver_team: str | None
    step_up: bool
    needs_person: bool
    scopes: list[str]
    output_shape: str | None
    response_schema: dict[str, JsonValue] | None
    code: CodeSettings | None


def operation_defaults() -> OperationDefaults:
    """A fresh copy, since an operation holds its own `scopes` list."""
    return {
        "body_encoding": None,
        "response_transform": None,
        "timeout_ms": None,
        "approval_mode": None,
        "reviewer_role": None,
        "approvers": 1,
        "approver_team": None,
        "step_up": False,
        "needs_person": False,
        "scopes": [],
        "output_shape": None,
        "response_schema": None,
        "code": None,
    }


class Operation(OperationDefaults):
    """An operation as the service reads and builds it. `stub` is the operation's example answer, read from its example
    mock and written back to it; a built operation names no tenant, module or position, `put` sets them."""

    id: str
    tool_id: str
    name: str
    description: str
    access: Literal["read", "write"]
    enabled: bool
    executor: str
    method: str | None
    path: str | None
    headers: list[Header]
    body: str | None
    input: list[InputField]
    masked_output: list[str]
    binding: Binding | None
    rate_limit_per_min: int
    requires_approval: bool | None
    amount_max: Decimal | float | None
    stub: NotRequired[JsonValue]
    # The rule that reads a failure inside a 200 answer, set by the plugin host when a call resolves the operation.
    error_when: NotRequired[dict[str, JsonValue] | None]
    # Why a plugin's tool is hidden from a team, set when a call resolves it.
    hidden_reason: NotRequired[str]
    # A route-owned operation says it makes a draft (mcp_tools.py), and a plugin's names the window its calls share.
    draft: NotRequired[bool]
    rate_key: NotRequired[str]
    tenant_id: NotRequired[str]
    module_id: NotRequired[str]
    position: NotRequired[int]


class StoredOperation(TypedDict, total=False):
    """An operation inside a module's `baseline` as a reader sees it: a JSON copy taken at publish, so a number is text
    and a column added since is missing. It names every column, so a reviewed field is compared whenever the copy holds
    it. Read only (`published`): the module keeps and writes back the copy itself."""

    id: str
    tool_id: str
    name: str
    description: str
    access: str
    enabled: bool
    executor: str
    method: str | None
    path: str | None
    headers: list[Header]
    body: str | None
    body_encoding: str | None
    response_transform: str | None
    timeout_ms: int | None
    input: list[InputField]
    masked_output: list[str]
    binding: Binding | None
    rate_limit_per_min: int
    requires_approval: bool | None
    approval_mode: str | None
    reviewer_role: str | None
    amount_max: Decimal | float | str | None
    approvers: int
    approver_team: str | None
    step_up: bool
    needs_person: bool
    scopes: list[str]
    output_shape: str | None
    response_schema: dict[str, JsonValue] | None
    code: CodeSettings | None
    stub: JsonValue
    tenant_id: str
    module_id: str
    position: int


STORED_OPERATIONS = TypeAdapter(list[StoredOperation])


def published(baseline: list[dict[str, JsonValue]]) -> list[StoredOperation]:
    """The published operations a module's baseline holds, with the keys a reader compares."""
    return STORED_OPERATIONS.validate_python(baseline)


class ApprovalDefaults(TypedDict):
    workflow_team_id: str | None
    requested_by_email: str | None
    decider_team: str | None
    review_id: str | None


class Approval(ApprovalDefaults):
    """A workflow's approval to use some of a module's operations."""

    id: str
    workflow_id: str
    workflow_name: str
    environment: str
    major: int
    operations: list[str]
    constraints: str | None
    requested_by: str
    justification: str
    requested_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    status: str
    expires_at: datetime | None
    reason: str | None
    tenant_id: NotRequired[str]
    module_id: NotRequired[str]
    position: NotRequired[int]


class PinnedBy(TypedDict):
    """A workflow that pins a version."""

    id: str
    name: str


class VersionDefaults(TypedDict):
    review_id: str | None
    requested_at: datetime | None
    reviewer: str | None
    finding: str | None


class Version(VersionDefaults):
    id: str
    version: str
    major: int
    status: str
    published_at: datetime | None
    published_by: str
    note: str
    changes: list[Change]
    pinned_by: list[PinnedBy]
    reachability: list[Reachability]
    review_required: NotRequired[bool | None]
    policy: NotRequired[str | None]
    tenant_id: NotRequired[str]
    module_id: NotRequired[str]
    position: NotRequired[int]


def version_defaults() -> VersionDefaults:
    return {"review_id": None, "requested_at": None, "reviewer": None, "finding": None}


def approval_defaults() -> ApprovalDefaults:
    return {"workflow_team_id": None, "requested_by_email": None, "decider_team": None, "review_id": None}


class ModuleColumns(TypedDict):
    """The `tool_modules` columns of a module."""

    tenant_id: str
    id: str
    team_id: str | None
    name: str
    display_name: str
    system: str
    description: str
    status: str
    owner_team: str
    owner_contacts: list[str]
    auth: dict[str, JsonValue]
    timeout_ms: int
    data_classification: str
    catalog_id: str | None
    connection_id: str | None
    sign_in: str
    template_id: str | None
    protection: str | None
    reachable: bool
    drift: bool
    version: str
    pending: list[Change]
    # A JSON copy of the operations taken at publish, written back as read: `served_operations` reads it.
    baseline: list[dict[str, JsonValue]] | None
    revision: int
    created_at: datetime
    updated_at: datetime


class Module(ModuleColumns):
    """A module and its children, one aggregate: `egress_hosts` are the tenant allow-list entries it calls."""

    operations: list[Operation]
    versions: list[Version]
    approvals: list[Approval]
    egress_hosts: list[str]
    # Notes a call adds while it resolves the module, never stored (`put` writes the columns only): the address of
    # its account, the app's tool list and titles, and the reason a call is refused before it runs.
    endpoint: NotRequired[str]
    tools_on: NotRequired[list[str] | None]
    app_title: NotRequired[str]
    tool_titles: NotRequired[dict[str, str]]
    sign_in_needed: NotRequired[str]
    instance_missing: NotRequired[str]
    team_sign_in: NotRequired[dict[str, str | None]]
    app_off: NotRequired[dict[str, str | None]]
    account_choice: NotRequired[AccountChoice]
    plugin_settings: NotRequired[dict[str, JsonValue]]
    plugin_team: NotRequired[str | None]
    sandbox: NotRequired[bool]
    # The team's plugin version, read only by the plugin host: its tools (a manifest's `Tool`, by name) and headers.
    plugin_tools: NotRequired[object]
    plugin_headers: NotRequired[dict[str, str]]
    plugin_off: NotRequired[str]
    account_missing: NotRequired[str]
    account_not_yours: NotRequired[str]
    sandbox_required: NotRequired[str]
    package_missing: NotRequired[str]


class ModuleRef(TypedDict):
    """What an account's sign-in reads of a module: its tenant, team, account and the address its call goes to."""

    tenant_id: str
    team_id: str | None
    connection_id: str | None
    endpoint: NotRequired[str]


class OperationName(TypedDict):
    name: str


class CardModule(ModuleColumns):
    """A module as the Apps grid counts it: each operation's name only."""

    operations: list[OperationName]


class ModuleGrants(TypedDict):
    """What decides whether a team sees a module: its team and its approvals."""

    id: str
    team_id: str | None
    approvals: list[Approval]


class ChildrenOf(TypedDict):
    operations: list[Operation]
    versions: list[Version]
    approvals: list[Approval]
    egress_hosts: list[str]


class ServiceEvent(TypedDict):
    """The keywords of `outbox.add`: an event a write reports in its own transaction."""

    tenant_id: str
    team_id: str | None
    name: str
    key: str
    actor: str | None
    payload: dict[str, JsonValue]


MODULE_COLUMNS = TypeAdapter(ModuleColumns)
OPERATION = TypeAdapter(Operation)


class ColumnDefaults(OperationDefaults):
    """What `module_operations` stores for a key a row leaves out: a column's default (`executor`, `headers`), null for
    a nullable column, and an empty list for `input` and `masked_output`. A published copy taken before a key existed
    in it restores with these, as an insert without the key wrote them."""

    executor: str
    method: str | None
    path: str | None
    headers: list[Header]
    body: str | None
    input: list[InputField]
    masked_output: list[str]
    binding: Binding | None
    requires_approval: bool | None
    amount_max: Decimal | float | None


def column_defaults() -> ColumnDefaults:
    """A fresh copy, since the lists are the operation's own."""
    return {
        **operation_defaults(),
        "executor": "http",
        "method": None,
        "path": None,
        "headers": [],
        "body": None,
        "input": [],
        "masked_output": [],
        "binding": None,
        "requires_approval": None,
        "amount_max": None,
    }


def restored_operation(copy: StoredOperation) -> Operation:
    """An operation from a stored JSON copy of one (a module's `baseline`, the seed's fields), with every key the copy
    leaves out filled as the table fills it; its numbers may be text."""
    return OPERATION.validate_python({**column_defaults(), **copy})


VERSION = TypeAdapter(Version)
APPROVAL = TypeAdapter(Approval)

# Service events this store reports, written in the transaction that makes the change: a workflow's access
# request and a version's review each start a system workflow.
service_outbox = outbox_table(metadata)

# The tables of a module's children; the egress hosts are read apart.
CHILDREN: dict[str, sa.Table] = {
    "operations": module_operations,
    "versions": module_versions,
    "approvals": module_approvals,
}

Aggregate = Module

# The allow-list's host column, named here without importing store.egress (which imports this module).
_listed_hosts = sa.table("egress_hosts", sa.column("tenant_id"), sa.column("host"))


def served_operations(agg: Module) -> list[Operation]:
    """The module's operations as calls see them. While edits are staged (a baseline exists), that is the published
    operations: an operation added since is not served, and every reviewed field (and the call shape) comes from the
    published one, so nothing Security has not approved reaches a call, the tools list or an agent's grants."""
    baseline, ops = agg["baseline"], agg["operations"]
    if baseline is None:
        return ops
    published = {o["id"]: dict(o) for o in baseline if "id" in o}
    out: list[Operation] = []
    for op in ops:
        before = published.get(op["id"])
        if before is None:
            continue
        # A baseline written before a field existed holds none of it and keeps the operation's. The copy's numbers
        # are text, so the merged operation is checked as a stored one is.
        shape = {k: before.get(k) for k in CALL_SHAPE}
        # A copy without headers sends none: the table's default (column_defaults), as a call read a missing list.
        shape["headers"] = shape["headers"] or []
        out.append(OPERATION.validate_python({**op, **shape, **{k: before[k] for k in REVIEWED if k in before}}))
    return out


# A tool's title as people see it (module, operation name), the grantable list's `tool_title`: the service wires it
# with the plugin host's manifest titles, which this layer cannot read.
TitleOf = Callable[[ModuleColumns, str], str | None]


def template_card(agg: Aggregate) -> tuple[TemplateKind, str]:
    """Where a module comes from and the id of its app card (Apps.cards): a plugin's and a built-in app's card is
    named by the module's template slot, a custom app's by its account, and a team's own module by the module."""
    template = str(agg.get("template_id") or "")
    if template.startswith("plugin:"):
        return "plugin", template
    if template.startswith("builtin:"):
        return "builtin", template
    if agg.get("connection_id"):
        return "custom", str(agg["connection_id"])
    return "custom", f"module:{agg['id']}"


def _cut(text: object) -> str | None:
    words = str(text or "").strip()
    return None if not words else words if len(words) <= DESCRIPTION_MAX else words[: DESCRIPTION_MAX - 1] + "…"


def catalog_of(agg: Aggregate, *, deleted: bool = False, titles: TitleOf | None = None) -> ToolModule:
    """What the agents lane's catalogue copy keeps of a module: its served operations only, so a staged edit Security
    has not approved never reaches another service's list. `titles` names each tool as the grantable list does; without
    it an operation's title is null."""
    ops = [] if deleted else served_operations(agg)
    kind, card = template_card(agg)
    return ToolModule(
        id=str(agg["id"]),
        name=str(agg["name"]),
        title=agg.get("display_name"),
        app=agg.get("system"),
        owner_team=agg.get("team_id"),
        status=agg.get("status"),
        version=agg.get("version"),
        template_kind=kind,
        app_card_id=card,
        operations=[
            ToolOperation(
                id=str(o["id"]),
                name=str(o["name"]),
                title=titles(agg, str(o["name"])) if titles is not None else None,
                description=_cut(o.get("description")),
                access=str(o["access"]),
                requires_approval=bool(o.get("requires_approval")),
                enabled=bool(o.get("enabled", True)),
            )
            for o in ops
        ],
        deleted=deleted,
    )


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None if value is None else str(value)


def team_grants(agg: Module) -> dict[str, ToolTeamStateChanged]:
    """Each other team's grant of the module, from its approved workflow approvals: the union of their operations,
    ending at the latest end (none if any approval has none). A team with only requested, refused or revoked
    approvals holds no grant."""
    by_team: dict[str, list[Approval]] = {}
    for a in agg["approvals"]:
        team = a.get("workflow_team_id")
        if team and team != agg.get("team_id") and a.get("status") == "approved":
            by_team.setdefault(str(team), []).append(a)
    out: dict[str, ToolTeamStateChanged] = {}
    for team, on in by_team.items():
        ends = [a.get("expires_at") for a in on]
        out[team] = ToolTeamStateChanged(
            id=f"approval:{agg['id']}",
            module_id=str(agg["id"]),
            via="approval",
            operations=sorted({n for a in on for n in a["operations"]}),
            expires_at=None if any(e is None for e in ends) else max(_iso(e) or "" for e in ends),
        )
    return out


async def report_module(
    c: AsyncConnection,
    agg: Aggregate,
    before: Aggregate | None,
    revision: int,
    *,
    deleted: bool = False,
    titles: TitleOf | None = None,
) -> None:
    """The catalogue events of one module write, on its transaction: `tool.module.published` for a new module or a new
    version, `tool.module.changed` for any other change the copy holds (or a delete), and `tool.team_state.changed`
    for each team whose grant changed. A write that changes none of that reports nothing.

    The catalogue event goes out on the module's team, or the acting team for a workspace-level module; with neither
    (a start-up install of a plugin) it is left to the agents lane's resync, which reads `catalog_events`."""
    tenant = str(agg["tenant_id"])
    now = catalog_of(agg, deleted=deleted, titles=titles)
    was = None if before is None else catalog_of(before, titles=titles)
    route = agg.get("team_id") or acting_team()
    if route is not None and now != was:
        new = was is None or now.version != was.version or (now.status == "published" and was.status != "published")
        payload = ToolPublished(**now.model_dump()) if new and not deleted else ToolChanged(**now.model_dump())
        payload = payload.fitted(revision)
        event = Event(name=payload.kind, tenant_id=tenant, team_id=route, revision=revision, payload=payload)
        await add_event(c, service_outbox, event)
    grants, held = team_grants(agg), {} if before is None else team_grants(before)
    for team in sorted(set(grants) | set(held)):
        state = grants.get(team)
        if deleted or state is None:
            # A grant withdrawn whole, or the module gone: the team's row becomes a tombstone.
            state = (held[team] if team in held else grants[team]).model_copy(update={"deleted": True})
        if state == held.get(team):
            continue
        event = Event(name=state.kind, tenant_id=tenant, team_id=team, revision=revision, payload=state)
        # Two teams' grants of one module share an id and a revision, so the key names the team.
        await add_event(c, service_outbox, event, key=f"{team}:{event.key()}")


class RetiredAccessError(RuntimeError):
    """A stored operation names an access class that no longer exists ("money_movement"). It is refused rather than
    read as anything else: such a database predates Read and Write only and is rebuilt by `make up`."""


ACCESS_CLASSES = frozenset({"read", "write"})


class HostNotAllowedError(RuntimeError):
    """A module names a host the tenant's egress allow-list does not hold."""

    def __init__(self, host: str) -> None:
        super().__init__(host)
        self.host = host


class StaleModuleError(RuntimeError):
    """`put` found a newer revision than the one the caller read: someone else changed the module first."""


# Why a read crosses teams: another service asks on a run's behalf, and the run's grants and approval token decide.
RUN_PATHS = "a run's call or grant list is authorized by its grants and approval token"
# Why the start-up move of sign-in header keys reads every team's headers: it finds the modules to move, then acts on
# each in its own team; it reads header names and references, never a secret.
HEADER_KEYS = "the start-up move of sign-in header keys finds each module whose tools still carry one"


@contextmanager
def _as_team(team_id: str | None) -> Generator[None]:
    """Act as `team_id` for a lookup that names it; otherwise keep the request's acting team."""
    if team_id is not None:
        with acting_as(team_id):
            yield
    else:
        with nullcontext():
            yield


def team_modules() -> sa.ColumnElement[bool]:
    """The acting team's modules and the tenant's workspace-level ones (no team); every module with no acting team.
    The team rule for `tool_modules`, which the database holds only to its tenant (tools_0086)."""
    team = acting_team()
    if team is None:
        return sa.true()
    t = tool_modules.c
    return sa.or_(t.team_id == team, t.team_id.is_(None))


def granted(tenant_id: str, team: str | None = None) -> sa.ColumnElement[bool]:
    """Modules approved for one of the acting team's (or `team`'s) workflows: the explicit grant across teams."""
    team = team or acting_team()
    if team is None:
        return sa.false()
    a = module_approvals.c
    # An approval past its end date opens nothing (`expired` is never stored), as `directory.grant_reaches` decides.
    live = sa.or_(a.expires_at.is_(None), a.expires_at > datetime.now(UTC))
    return tool_modules.c.id.in_(
        sa.select(a.module_id).where(a.tenant_id == tenant_id, a.workflow_team_id == team, a.status == "approved", live)
    )


def in_security_review(tenant_id: str) -> sa.ColumnElement[bool]:
    """Modules with a version waiting on its security review, in any team: what the workspace's Security team reads,
    and changes nothing of, when the service has found the caller decides those reviews (`reviews.decide` there)."""
    v = module_versions.c
    return tool_modules.c.id.in_(
        sa.select(v.module_id).where(v.tenant_id == tenant_id, v.status == "in_review", v.review_id.is_not(None))
    )


def seen_by(tenant_id: str, team: str) -> sa.ColumnElement[bool]:
    """`team`'s own modules, workspace-level ones (no team) and those approved for one of its workflows, named in the
    query for a caller whose request reads tenant-wide (the dev header caller); beside `team_modules`, never instead."""
    t = tool_modules.c
    return sa.or_(t.team_id == team, t.team_id.is_(None), granted(tenant_id, team))


def grant_views(now: datetime, expiring: timedelta) -> dict[str, sa.ColumnElement[bool]]:
    """The Access tab's views of an approval, by view: approved and not past its end is active (and expiring within
    `expiring`), requested waits, an approval past its end is expired, and a rejected or revoked one has ended."""
    a = module_approvals.c
    past = sa.and_(a.status == "approved", a.expires_at.isnot(None), a.expires_at < now)
    active = sa.and_(a.status == "approved", sa.or_(a.expires_at.is_(None), a.expires_at >= now))
    return {
        "active": active,
        "expiring": sa.and_(active, a.expires_at.isnot(None), a.expires_at < now + expiring),
        "requested": a.status == "requested",
        "expired": sa.or_(a.status == "expired", past),
        "ended": a.status.in_(("rejected", "revoked")),
        # A comparison, not `sa.true()`: SQL Server renders that as a bare 1, which a CASE refuses as a condition.
        "all": a.id.is_not(None),
    }


def _cards_stamp() -> sa.Table:
    """team_defaults, declared in store/team_defaults.py on this module's metadata (which that module imports, so it
    cannot be imported here); the package imports it before any store runs."""
    return metadata.tables["team_defaults"]


async def forget_cards(c: AsyncConnection, tenant_id: str, team: sa.ColumnElement[bool]) -> None:
    """Clears the app card stamp (store/app_cards.py) of the teams `team` names, in the caller's transaction, so their
    next list rebuilds."""
    t = _cards_stamp()
    await c.execute(t.update().where(t.c.tenant_id == tenant_id, team, team_visible(t)).values(cards_stamp=None))


def _team_of(team_id: str | None) -> sa.ColumnElement[bool]:
    """The teams whose app cards a module of `team_id` is part of: its own, or every team the caller acts in for a
    workspace-level module (no team)."""
    return _cards_stamp().c.team_id == team_id if team_id else sa.true()


class HeaderHolder(TypedDict):
    """An operation's headers with its place: tenant, team and module."""

    tenant_id: str
    team_id: str
    module_id: str
    headers: list[Header]


class SecretOperation(TypedDict):
    """An operation as the Secrets page reads it: where it is called and the headers it sends."""

    module_id: str
    id: str
    name: str
    path: str | None
    headers: list[Header]


# The keys of a published operation (a module's `baseline`, a JSON copy taken at publish) the Secrets page reads. Read
# only: the copy is never written back from this shape.
class PublishedOperation(TypedDict, total=False):
    id: str
    name: str
    path: str | None
    headers: list[Header]


class SecretReader(TypedDict):
    """A module as the Secrets page reads it: its published operations and each operation's path and headers."""

    id: str
    display_name: str
    baseline: list[PublishedOperation] | None
    operations: list[SecretOperation]


HEADER_HOLDER = TypeAdapter(HeaderHolder)
SECRET_OPERATION = TypeAdapter(SecretOperation)
PUBLISHED_OPERATIONS = TypeAdapter(list[PublishedOperation])


class ModuleStore(Store):
    # A module and its children land together (TRANSACTION); a write lands only against the revision read (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})
    role = ROLE
    system_role = SYSTEM_ROLE
    # Set by the service at start (`__main__`), so the catalogue events title tools as the grantable list does.
    titles: TitleOf | None = None

    async def _children(
        self, c: AsyncConnection, tenant_id: str, ids: list[str], within: sa.Select[Any] | None = None
    ) -> dict[str, ChildrenOf]:
        """The children of the modules `ids`. A read of every module passes the query that chose them as `within`, which
        the children are matched against in SQL: a list of ids is one parameter each, past SQL Server's 2,100 at about
        2,090 modules."""
        chosen = ids if within is None else within
        examples = await self._examples(c, tenant_id, ids, within)
        out: dict[str, ChildrenOf] = {
            i: {"operations": [], "versions": [], "approvals": [], "egress_hosts": []} for i in ids
        }

        def rows(table: sa.Table) -> sa.Select[Any]:
            return (
                table.select()
                .where(table.c.tenant_id == tenant_id, table.c.module_id.in_(chosen))
                .order_by(table.c.module_id, table.c.position)
            )

        for r in (await c.execute(rows(module_operations))).mappings():
            if r["access"] not in ACCESS_CLASSES:
                raise RetiredAccessError(
                    f"operation {r['name']} in {r['module_id']} has access {r['access']!r}, which is no longer an "
                    "access class; rebuild the database with `make up`"
                )
            stub = examples.get((r["module_id"], str(r["name"])), NO_EXAMPLE)
            out[r["module_id"]]["operations"].append(OPERATION.validate_python({**r, "stub": stub}))
        for r in (await c.execute(rows(module_versions))).mappings():
            out[r["module_id"]]["versions"].append(VERSION.validate_python(r))
        for r in (await c.execute(rows(module_approvals))).mappings():
            out[r["module_id"]]["approvals"].append(APPROVAL.validate_python(r))
        h = module_egress_hosts.c
        q = (
            sa.select(h.module_id, h.host)
            .where(h.tenant_id == tenant_id, h.module_id.in_(chosen))
            .order_by(module_egress_hosts.c.module_id, module_egress_hosts.c.position)
        )
        for module_id, host in await c.execute(q):
            out[module_id]["egress_hosts"].append(host)
        return out

    @staticmethod
    def _of(row: RowMapping, kids: ChildrenOf) -> Module:
        """A module row and its children, checked against the aggregate's shape."""
        return {**MODULE_COLUMNS.validate_python(dict(row)), **kids}

    @staticmethod
    async def _examples(
        c: AsyncConnection, tenant_id: str, ids: list[str], within: sa.Select[Any] | None = None
    ) -> dict[tuple[str, str], JsonValue]:
        """Each operation's example answer, by (module, operation name): the body of its example mock."""
        m = operation_mocks.c
        chosen = m.module_id.in_(ids if within is None else within)
        q = sa.select(m.module_id, m.operation, m.body).where(
            m.tenant_id == tenant_id, chosen, m.environment == EXAMPLE, m.is_default == sa.true()
        )
        return {(str(r.module_id), str(r.operation)): r.body for r in await c.execute(q)}

    @staticmethod
    async def _write_examples(c: AsyncConnection, agg: Module, at: datetime) -> None:
        """An operation's `stub` written as its example mock: the body of the one there, or a new one. An operation with
        no example leaves it as it is."""
        tenant, module = agg["tenant_id"], agg["id"]
        held = await ModuleStore._examples(c, tenant, [module])
        m = operation_mocks.c
        for o in agg["operations"]:
            body, name = o.get("stub"), o["name"]
            if body is None or body == NO_EXAMPLE or held.get((module, name), NO_EXAMPLE) == body:
                continue
            where = (m.tenant_id == tenant, m.module_id == module, m.operation == name, m.environment == EXAMPLE)
            if (module, name) in held:
                await c.execute(operation_mocks.update().where(*where, m.is_default == sa.true()).values(body=body))
                continue
            last = (await c.execute(sa.select(sa.func.max(m.position)).where(*where))).scalar()
            await c.execute(
                operation_mocks.insert().values(
                    tenant_id=tenant, id=new_id("mck"), module_id=module, operation=name,
                    environment=EXAMPLE, position=int(last or 0) + 1, name="Example answer", match={}, status=200,
                    body=body, headers={}, delay_ms=0, timeout=False, is_default=True, from_call_id=None,
                    created_by=EXAMPLE_AUTHOR, created_at=at, updated_at=at,
                )
            )  # fmt: skip

    async def all(self, tenant_id: str) -> list[Module]:
        """The modules the acting team reads: its own, workspace-level ones (no team) and those approved for one
        of its workflows, which is the explicit grant across teams. Every module with no acting team."""
        where = sa.and_(tool_modules.c.tenant_id == tenant_id, sa.or_(team_modules(), granted(tenant_id)))
        async with self.tx() as c:
            q = tool_modules.select().where(where).order_by(tool_modules.c.created_at.desc(), tool_modules.c.id.desc())
            rows = list((await c.execute(q)).mappings())
            kids = await self._children(
                c, tenant_id, [r["id"] for r in rows], sa.select(tool_modules.c.id).where(where)
            )
        return [self._of(r, kids[r["id"]]) for r in rows]

    async def seen(self, tenant_id: str) -> list[ModuleGrants]:
        """The modules `all` reads, each with only its `id`, `team_id` and `approvals`: what decides whether a team
        sees it and which workflow names its grants hold. A list that names the visible modules and loads in full only
        the ones its page shows asks for this, then `chosen`."""
        where = sa.and_(tool_modules.c.tenant_id == tenant_id, sa.or_(team_modules(), granted(tenant_id)))
        a = module_approvals.c
        async with self.tx() as c:
            q = sa.select(tool_modules.c.id, tool_modules.c.team_id).where(where)
            rows = list((await c.execute(q)).mappings())
            held: dict[str, list[Approval]] = {r["id"]: [] for r in rows}
            q = (
                module_approvals.select()
                .where(a.tenant_id == tenant_id, a.module_id.in_(sa.select(tool_modules.c.id).where(where)))
                .order_by(a.module_id, a.position)
            )
            for r in (await c.execute(q)).mappings():
                held[r["module_id"]].append(APPROVAL.validate_python(r))
        return [{"id": r["id"], "team_id": r["team_id"], "approvals": held[r["id"]]} for r in rows]

    async def card_modules(
        self, tenant_id: str, team_id: str, *, chosen: tuple[Sequence[str], Sequence[str], Sequence[str]] | None = None
    ) -> list[CardModule]:
        """The team's own and workspace-level modules (no team) with each operation's name, what the Apps grid's cards
        count and match: every one, or with `chosen` (ids, template ids, names of modules bound to no account) only
        those, for one page of cards. A grant to one of the team's workflows does not put another team's module on its
        grid."""
        t = tool_modules.c
        where = sa.and_(t.tenant_id == tenant_id, team_modules(), sa.or_(t.team_id == team_id, t.team_id.is_(None)))
        if chosen is not None:
            ids, templates, names = (list(x) for x in chosen)
            if not (ids or templates or names):
                return []
            where = sa.and_(
                where,
                sa.or_(
                    t.id.in_(ids), t.template_id.in_(templates), sa.and_(t.name.in_(names), t.connection_id.is_(None))
                ),
            )
        o = module_operations.c
        async with self.tx() as c:
            q = tool_modules.select().where(where).order_by(t.created_at.desc(), t.id.desc())
            rows = list((await c.execute(q)).mappings())
            ops = (
                sa.select(o.module_id, o.name)
                .where(o.tenant_id == tenant_id, o.module_id.in_(sa.select(t.id).where(where)))
                .order_by(o.module_id, o.position)
            )
            held: dict[str, list[str]] = {}
            for module_id, name in await c.execute(ops):
                held.setdefault(str(module_id), []).append(str(name))
        return [
            {**MODULE_COLUMNS.validate_python(r), "operations": [{"name": n} for n in held.get(str(r["id"]), [])]}
            for r in rows
        ]

    async def headers(self, tenant_id: str, ids: Sequence[str]) -> dict[str, ModuleColumns]:
        """The module rows named by `ids` that the acting team reads, by id, with no operations, versions or
        approvals: what a log row shows of its module (its names and template)."""
        if not ids:
            return {}
        async with self.tx() as c:
            q = tool_modules.select().where(
                tool_modules.c.tenant_id == tenant_id,
                sa.or_(team_modules(), granted(tenant_id)),
                tool_modules.c.id.in_(list(ids)),
            )
            return {r["id"]: MODULE_COLUMNS.validate_python(r) for r in (await c.execute(q)).mappings()}

    async def chosen(self, tenant_id: str, ids: Sequence[str], *, reviews: bool = False) -> list[Module]:
        """The modules named by `ids` that the acting team reads (as `all`), in `ids`' order: a list's page. With
        `reviews` (a Security reviewer's queue), also those waiting on their security review."""
        if not ids:
            return []
        seen = [team_modules(), granted(tenant_id), *([in_security_review(tenant_id)] if reviews else [])]
        async with self.tx() as c:
            q = tool_modules.select().where(
                tool_modules.c.tenant_id == tenant_id,
                sa.or_(*seen),
                tool_modules.c.id.in_(list(ids)),
            )
            rows = {r["id"]: r for r in (await c.execute(q)).mappings()}
            kids = await self._children(c, tenant_id, list(rows))
        return [self._of(rows[i], kids[i]) for i in ids if i in rows]

    async def grants(
        self,
        tenant_id: str,
        q: ListParams,
        *,
        view: sa.ColumnElement[bool],
        views: Mapping[str, sa.ColumnElement[bool]],
    ) -> tuple[ListPage, dict[str, int]]:
        """One page of the approvals on the modules the acting team reads, newest request first, searched by workflow,
        module or requester, in `view`; and how many of them, unsearched, each of `views` holds."""
        a, t = module_approvals.c, tool_modules.c
        seen = sa.and_(t.tenant_id == tenant_id, sa.or_(team_modules(), granted(tenant_id)))
        joined = module_approvals.join(tool_modules, sa.and_(t.tenant_id == a.tenant_id, t.id == a.module_id))
        listed = sa.select(*module_approvals.c, t.display_name.label("module_name")).select_from(joined).where(seen)
        async with self.tx() as c:
            page = await list_page(
                c,
                listed.where(view),
                q,
                search=[a.workflow_name, a.workflow_id, t.display_name, t.name, a.requested_by],
                sortable={"workflowName": a.workflow_name, "status": a.status, "requestedAt": a.requested_at},
                default_sort=a.requested_at.desc(),
            )
            sums = [sa.func.sum(sa.case((where, 1), else_=0)).label(name) for name, where in views.items()]
            counted = sa.select(*sums).select_from(joined).where(seen)
            row = (await c.execute(counted)).mappings().one()
        return page, {name: int(row[name] or 0) for name in views}

    async def all_teams(self, tenant_id: str) -> list[Module]:
        """Every team's modules: for what another service asks on a run's behalf (the operations an agent or workflow
        may be granted, a call's resolution), which the run's grants and its approval token decide, not the caller's
        team."""
        where = sa.and_(tool_modules.c.tenant_id == tenant_id, any_team(tool_modules, RUN_PATHS))
        async with self.tx() as c:
            q = tool_modules.select().where(where).order_by(tool_modules.c.created_at.desc(), tool_modules.c.id.desc())
            rows = list((await c.execute(q)).mappings())
            kids = await self._children(
                c, tenant_id, [r["id"] for r in rows], sa.select(tool_modules.c.id).where(where)
            )
        return [self._of(r, kids[r["id"]]) for r in rows]

    async def header_holders(self, tenant_id: str | None = None) -> list[HeaderHolder]:
        """Every team module's operation that carries a header, every tenant's or `tenant_id`'s: its tenant, team,
        module and headers."""
        m, ops = tool_modules.c, module_operations.c
        team_module = sa.and_(m.team_id.is_not(None), any_team(tool_modules, HEADER_KEYS))
        if tenant_id is not None:
            tenants = [tenant_id]
        else:
            # The system role reads no header (tools_0083): it lists the tenants, and each tenant's headers are read
            # in that tenant. One read per tenant, once at start.
            async with self.system_tx(HEADER_KEYS) as c:
                q = sa.select(m.tenant_id).where(team_module).distinct().order_by(m.tenant_id)
                tenants = [str(t) for t in (await c.execute(q)).scalars()]
        on = sa.and_(ops.tenant_id == m.tenant_id, ops.module_id == m.id)
        found: list[HeaderHolder] = []
        for tenant in tenants:
            q = (
                sa.select(m.tenant_id, m.team_id, ops.module_id, ops.headers)
                .select_from(tool_modules.join(module_operations, on))
                .where(m.tenant_id == tenant, team_module)
                .order_by(ops.module_id, ops.id)
            )
            with isolation.tenant_wide(HEADER_KEYS, tenant_id=tenant):
                async with self.tx() as c:
                    found += [HEADER_HOLDER.validate_python(r) for r in (await c.execute(q)).mappings() if r["headers"]]
        return found

    async def names(self, tenant_id: str, team_id: str | None = None) -> set[str]:
        """Module names of the acting team (or `team_id`), plus workspace-level names: a name is unique per team, so the
        check before a create does not see another team's."""
        with _as_team(team_id):
            q = sa.select(tool_modules.c.name).where(tool_modules.c.tenant_id == tenant_id, team_modules())
            async with self.tx() as c:
                return {str(r[0]) for r in await c.execute(q)}

    async def secret_readers(self, tenant_id: str) -> list[SecretReader]:
        """Each module's id, display name and baseline with its operations' id, name, path and headers: what the
        Secrets page needs to say which operations read a secret, in two reads instead of every child table."""
        ops = module_operations.c
        async with self.tx() as c:
            q = sa.select(tool_modules.c.id, tool_modules.c.display_name, tool_modules.c.baseline).where(
                tool_modules.c.tenant_id == tenant_id, sa.or_(team_modules(), granted(tenant_id))
            )
            rows: dict[str, SecretReader] = {
                r["id"]: {
                    "id": r["id"],
                    "display_name": r["display_name"],
                    "baseline": None if r["baseline"] is None else PUBLISHED_OPERATIONS.validate_python(r["baseline"]),
                    "operations": [],
                }
                for r in (await c.execute(q)).mappings()
            }
            q = (
                sa.select(ops.module_id, ops.id, ops.name, ops.path, ops.headers)
                .where(ops.tenant_id == tenant_id)
                .order_by(ops.module_id, ops.position)
            )
            for r in (await c.execute(q)).mappings():
                if r["module_id"] in rows:
                    rows[r["module_id"]]["operations"].append(SECRET_OPERATION.validate_python(r))
        return list(rows.values())

    async def get(self, tenant_id: str, module_id: str, *, reviews: bool = False) -> Module | None:
        """The module when the acting team reads it (as `all`), or with `reviews` (a Security reviewer) when it waits on
        its security review; None otherwise, so its routes answer 404."""
        seen = [team_modules(), granted(tenant_id), *([in_security_review(tenant_id)] if reviews else [])]
        async with self.tx() as c:
            q = tool_modules.select().where(
                tool_modules.c.tenant_id == tenant_id,
                tool_modules.c.id == module_id,
                sa.or_(*seen),
            )
            row = (await c.execute(q)).mappings().first()
            if row is None:
                return None
            return self._of(row, (await self._children(c, tenant_id, [module_id]))[module_id])

    async def get_any(self, tenant_id: str, module_id: str) -> Module | None:
        """The module in any team: for a call's resolution and for a decision agents-service already held to the review
        rules, both authorized by what they carry rather than by the caller's team."""
        async with self.tx() as c:
            q = tool_modules.select().where(
                tool_modules.c.tenant_id == tenant_id, tool_modules.c.id == module_id, any_team(tool_modules, RUN_PATHS)
            )
            row = (await c.execute(q)).mappings().first()
            if row is None:
                return None
            return self._of(row, (await self._children(c, tenant_id, [module_id]))[module_id])

    async def operation_named(
        self, tenant_id: str, name: str, team_id: str | None = None
    ) -> tuple[Module, Operation] | None:
        """The module holding operation `name` in the acting team (or `team_id`), and the operation. Another team's
        module of the same name is not seen. A workspace-level module is used when the team has no copy of its own."""
        with _as_team(team_id):
            async with self.tx() as c:
                q = (
                    sa.select(tool_modules.c.id, tool_modules.c.team_id)
                    .select_from(
                        module_operations.join(
                            tool_modules,
                            sa.and_(
                                module_operations.c.tenant_id == tool_modules.c.tenant_id,
                                module_operations.c.module_id == tool_modules.c.id,
                            ),
                        )
                    )
                    .where(
                        module_operations.c.tenant_id == tenant_id,
                        module_operations.c.name == name,
                        sa.or_(team_modules(), granted(tenant_id)),
                    )
                )
                rows = list((await c.execute(q)).all())
            if not rows:
                return None
            team = team_id if team_id is not None else acting_team()
            own = next((r[0] for r in rows if r[1] == team), None) if team else None
            module_id = own if own is not None else rows[0][0]
            agg = await self.get(tenant_id, module_id)
        if agg is None:
            return None
        op = next((o for o in served_operations(agg) if o["name"] == name), None)
        if op is None:
            return None
        return agg, op

    async def names_taken(self, tenant_id: str, names: list[str], team_id: str | None = None) -> set[str]:
        """Which of `names` are already operation names in the acting team (or `team_id`), or on a workspace-level
        module. Another team's names are not taken."""
        if not names:
            return set()
        with _as_team(team_id):
            q = (
                sa.select(module_operations.c.name)
                .select_from(
                    module_operations.join(
                        tool_modules,
                        sa.and_(
                            module_operations.c.tenant_id == tool_modules.c.tenant_id,
                            module_operations.c.module_id == tool_modules.c.id,
                        ),
                    )
                )
                .where(
                    module_operations.c.tenant_id == tenant_id,
                    module_operations.c.name.in_(names),
                    team_modules(),
                )
            )
            async with self.tx() as c:
                return {r[0] for r in await c.execute(q)}

    async def put(
        self,
        agg: Module,
        *,
        expected_revision: int | None,
        seeded: bool = False,
        events: Sequence[ServiceEvent] = (),
        conn: AsyncConnection | None = None,
    ) -> Module:
        """Writes the whole aggregate. `expected_revision` None inserts a new module; otherwise the update lands only
        when the stored revision still equals it, else StaleModuleError. Returns the aggregate at its new revision.
        `seeded` writes revision 0, the dev seed's mark for a module nobody has edited. HostNotAllowedError when the
        module names a host the tenant's egress allow-list does not hold; nothing is written then. `events` are
        service events (`outbox.add` keywords) written with the change, so neither commits without the other. `conn`
        is a transaction the caller holds open (a savepoint around an insert that may lose a race)."""
        if conn is None:
            async with self.tx() as c:
                return await self.put(agg, expected_revision=expected_revision, seeded=seeded, events=events, conn=c)
        c = conn
        # Only the table's columns: a module as a call reaches it carries its connection's address, never stored.
        row = {k: v for k, v in agg.items() if k in tool_modules.c}
        hosts: list[str] = list(dict.fromkeys(agg["egress_hosts"]))
        if hosts:
            listed_q = sa.select(_listed_hosts.c.host).where(
                _listed_hosts.c.tenant_id == row["tenant_id"], _listed_hosts.c.host.in_(hosts)
            )
            listed = {r[0] for r in await c.execute(listed_q)}
            missing = [h for h in hosts if h not in listed]
            if missing:
                raise HostNotAllowedError(missing[0])
        before: Module | None = None
        if expected_revision is None:
            row["revision"] = 0 if seeded else 1
            await c.execute(tool_modules.insert().values(**row))
        else:
            row["revision"] = 0 if seeded else expected_revision + 1
            before = await self._held(c, str(row["tenant_id"]), str(row["id"]))
            done = await c.execute(
                tool_modules.update()
                .where(
                    tool_modules.c.tenant_id == row["tenant_id"],
                    tool_modules.c.id == row["id"],
                    tool_modules.c.revision == expected_revision,
                )
                .values(**row)
            )
            if done.rowcount == 0:
                raise StaleModuleError(row["id"])
            for table in (*CHILDREN.values(), module_egress_hosts):
                await c.execute(
                    table.delete().where(table.c.tenant_id == row["tenant_id"], table.c.module_id == row["id"])
                )
        # Every row names the same columns (an insert of many rows takes its columns from the first); a seeded or
        # older operation may predate response_transform and timeout_ms, an approval its team. Only the table's own
        # columns: a baseline or staged copy written before a column was dropped (self_approval) still carries it,
        # and a discard writes those copies back.
        children: tuple[
            tuple[sa.Table, list[Operation], ColumnDefaults],
            tuple[sa.Table, list[Version], VersionDefaults],
            tuple[sa.Table, list[Approval], ApprovalDefaults],
        ] = (
            (module_operations, agg["operations"], column_defaults()),
            (module_versions, agg["versions"], version_defaults()),
            (module_approvals, agg["approvals"], approval_defaults()),
        )
        for table, held, defaults in children:
            rows = [
                {
                    k: v
                    for k, v in {
                        **defaults,
                        **r,
                        "tenant_id": row["tenant_id"],
                        "module_id": row["id"],
                        "position": i,
                    }.items()
                    if k in table.c
                }
                for i, r in enumerate(held)
            ]
            if rows:
                await c.execute(table.insert(), rows)
        await self._write_examples(c, agg, agg["updated_at"])
        if hosts:
            links = [
                {"tenant_id": row["tenant_id"], "module_id": row["id"], "host": h, "position": i}
                for i, h in enumerate(hosts)
            ]
            await c.execute(module_egress_hosts.insert(), links)
        for event in events:
            await add_event(c, service_outbox, **event)
        # A seed refresh keeps revision 0, which no copy would take over its first write; the resync carries it.
        if not (seeded and before is not None):
            revision = int(row["revision"])
            await report_module(c, {**agg, "revision": revision}, before, revision, titles=self.titles)
        # A built-in app's card and a removed plugin's are built from its team's modules (Apps.cards).
        await forget_cards(c, agg["tenant_id"], _team_of(agg["team_id"]))
        return {**agg, "revision": row["revision"]}

    async def insert_if_missing(self, agg: Module) -> bool:
        """Inserts `agg` as a module nobody has edited (revision 0) unless one with its id is already there, as when two
        first calls race to write it. True when this call wrote it."""
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    await self.put(agg, expected_revision=None, seeded=True, conn=c)
            except IntegrityError:
                return False
        return True

    async def delete(self, tenant_id: str, module_id: str) -> bool:
        t = tool_modules.c
        async with self.tx() as c:
            found = await self._held(c, tenant_id, module_id)
            if found is None:
                return False
            done = await c.execute(tool_modules.delete().where(t.tenant_id == tenant_id, t.id == module_id))
            await forget_cards(c, tenant_id, _team_of(found["team_id"]))
            # One past the last write, as a copy takes a delete only over a lower revision.
            await report_module(c, found, found, int(found["revision"]) + 1, deleted=True, titles=self.titles)
            return done.rowcount > 0

    async def _held(self, c: AsyncConnection, tenant_id: str, module_id: str) -> Module | None:
        """The module as stored, on the writer's transaction: what a write's events are compared against."""
        t = tool_modules.c
        q = tool_modules.select().where(t.tenant_id == tenant_id, t.id == module_id)
        found = (await c.execute(q)).mappings().first()
        if found is None:
            return None
        return self._of(found, (await self._children(c, tenant_id, [module_id]))[module_id])

    async def count(self, tenant_id: str) -> int:
        q = (
            sa.select(sa.func.count())
            .select_from(tool_modules)
            .where(tool_modules.c.tenant_id == tenant_id, sa.or_(team_modules(), granted(tenant_id)))
        )
        async with self.tx() as c:
            return int((await c.execute(q)).scalar_one())
