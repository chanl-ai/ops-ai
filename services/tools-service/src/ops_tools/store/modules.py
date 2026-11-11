"""The tool-module registry: modules, their operations, versions, security reviews and workflow approvals.

A module and its children are one aggregate. The service reads it whole, changes it, and writes it back whole with
`put`, which replaces the children in the same transaction and lands only while the module's `revision` still equals
the one read, so two concurrent edits cannot silently overwrite each other.

Every table carries `tenant_id`; `tool_modules` also carries `team_id`, the team that owns the module. Row-level
security on them arrives with ops_identity, as the checkpointer does it.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager, nullcontext
from typing import Any, ClassVar, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.sql.schema import SchemaItem

from ops_service_kit.ids import new_id
from ops_store import Guarantee
from ops_store.outbox import add as add_event
from ops_store.outbox import outbox_table
from ops_store.schema import TEAM_OWNED
from ops_store.team_scope import acting_as, acting_team, any_team, team_visible

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
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("display_name", sa.String(200), nullable=False),
    sa.Column("system", sa.String(200), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("owner_team", sa.String(120), nullable=False),
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
    sa.Column("template_id", sa.String(120), index=True),
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
    sa.Column("updated_at", _TS, nullable=False),
    # Workflows pin a module by name, so a name is unique within a team. A workspace-level
    # module (null team) is unique on (tenant, name) so two shared copies cannot land.
    info=TEAM_OWNED,
)

_OWNED = tool_modules.c.team_id.isnot(None)
_SHARED = tool_modules.c.team_id.is_(None)
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
    sa.Column("name", sa.String(200), nullable=False),
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
)

# The mock "environment" holding an operation's example answer: what Mock answers when no test mock matches,
# what a system with no upstream answers in every environment, and what an output schema is inferred from. Apart from
# "test" on purpose: a test mock intercepts test-environment calls, and an example must not keep a Real run in test from
# reaching the system.
EXAMPLE = "example"
# An operation with no example answers this: what an import writes when the document gives none (registry._output).
NO_EXAMPLE: dict[str, Any] = {"ok": True}
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
    sa.Column("workflow_name", sa.String(200), nullable=False),
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
    sa.Column("requested_at", _TS, nullable=False),
    sa.Column("decided_by", sa.String(200)),
    sa.Column("decided_at", _TS),
    # requested, approved, rejected or revoked; `expired` is computed from expires_at and never stored.
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("expires_at", _TS),
    sa.Column("reason", sa.Text),
    # The team whose reviewers decide the request and the Human Tasks review deciding it; null on approvals
    # made before requests went to Reviews.
    sa.Column("decider_team", sa.String(64)),
    sa.Column("review_id", sa.String(64)),
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
    "enabled",
    "binding",
    "amount_max",
    "needs_person",
    *APPROVAL_POLICY,
)
OPERATION_DEFAULTS: dict[str, Any] = {
    "body_encoding": None,
    "response_transform": None,
    "timeout_ms": None,
    "approvers": 1,
    "approver_team": None,
    "step_up": False,
    "needs_person": False,
    "scopes": [],
    "output_shape": None,
    "response_schema": None,
    "code": None,
}
# Defaults per child table, for rows written before a column existed.
CHILD_DEFAULTS: dict[str, dict[str, Any]] = {
    "operations": OPERATION_DEFAULTS,
    "approvals": {"workflow_team_id": None, "requested_by_email": None, "decider_team": None, "review_id": None},
    "versions": {"review_id": None, "requested_at": None, "reviewer": None, "finding": None},
}

# Service events this store reports, written in the transaction that makes the change: a workflow's access
# request and a version's review each start a system workflow.
service_outbox = outbox_table(metadata)

CHILDREN: dict[str, sa.Table] = {
    "operations": module_operations,
    "versions": module_versions,
    "approvals": module_approvals,
}

Aggregate = dict[str, Any]
"""A module row's columns plus `operations`, `versions` and `approvals`, each a list of row dicts, and
`egress_hosts`, the tenant allow-list entries the module calls."""

# The allow-list's host column, named here without importing store.egress (which imports this module).
_listed_hosts = sa.table("egress_hosts", sa.column("tenant_id"), sa.column("host"))


def served_operations(agg: Aggregate) -> list[dict[str, Any]]:
    """The module's operations as calls see them. While edits are staged (a baseline exists), that is the published
    operations: an operation added since is not served, and every reviewed field (and the call shape) comes from the
    published one, so nothing Security has not approved reaches a call, the tools list or an agent's grants."""
    baseline = cast(list[dict[str, Any]] | None, agg.get("baseline"))
    ops = cast(list[dict[str, Any]], agg["operations"])
    if baseline is None:
        return ops
    published = {o["id"]: o for o in baseline}
    out: list[dict[str, Any]] = []
    for op in ops:
        before = published.get(op["id"])
        if before is None:
            continue
        # A baseline written before a field existed holds none of it and keeps the operation's.
        out.append(
            {
                **op,
                **{k: before.get(k) for k in CALL_SHAPE},
                **{k: before[k] for k in REVIEWED if k in before},
            }
        )
    return out


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


def _granted(tenant_id: str) -> sa.ColumnElement[bool]:
    """Modules approved for one of the acting team's workflows: the explicit grant across teams."""
    team = acting_team()
    if team is None:
        return sa.false()
    a = module_approvals.c
    return tool_modules.c.id.in_(
        sa.select(a.module_id).where(a.tenant_id == tenant_id, a.workflow_team_id == team, a.status == "approved")
    )


class ModuleStore:
    # A module and its children land together (TRANSACTION); a write lands only against the revision read (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def _children(self, c: AsyncConnection, tenant_id: str, ids: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, list[dict[str, Any]]]] = {i: {k: [] for k in CHILDREN} for i in ids}
        for key, table in CHILDREN.items():
            q = (
                table.select()
                .where(table.c.tenant_id == tenant_id, table.c.module_id.in_(ids))
                .order_by(table.c.module_id, table.c.position)
            )
            for r in (await c.execute(q)).mappings():
                if key == "operations" and r["access"] not in ACCESS_CLASSES:
                    raise RetiredAccessError(
                        f"operation {r['name']} in {r['module_id']} has access {r['access']!r}, which is no longer an "
                        "access class; rebuild the database with `make up`"
                    )
                out[r["module_id"]][key].append(dict(r))
        examples = await self._examples(c, tenant_id, ids)
        for i in ids:
            for o in out[i]["operations"]:
                o["stub"] = examples.get((i, str(o["name"])), NO_EXAMPLE)
        hosts: dict[str, list[str]] = {i: [] for i in ids}
        q = (
            sa.select(module_egress_hosts.c.module_id, module_egress_hosts.c.host)
            .where(module_egress_hosts.c.tenant_id == tenant_id, module_egress_hosts.c.module_id.in_(ids))
            .order_by(module_egress_hosts.c.module_id, module_egress_hosts.c.position)
        )
        for module_id, host in await c.execute(q):
            hosts[module_id].append(host)
        return {i: {**out[i], "egress_hosts": hosts[i]} for i in ids}

    @staticmethod
    async def _examples(c: AsyncConnection, tenant_id: str, ids: list[str]) -> dict[tuple[str, str], Any]:
        """Each operation's example answer, by (module, operation name): the body of its example mock."""
        m = operation_mocks.c
        q = sa.select(m.module_id, m.operation, m.body).where(
            m.tenant_id == tenant_id, m.module_id.in_(ids), m.environment == EXAMPLE, m.is_default.is_(True)
        )
        return {(str(r.module_id), str(r.operation)): r.body for r in await c.execute(q)}

    @staticmethod
    async def _write_examples(c: AsyncConnection, agg: Aggregate, at: Any) -> None:
        """An operation's `stub` written as its example mock: the body of the one there, or a new one. An operation with
        no example leaves it as it is."""
        tenant, module = str(agg["tenant_id"]), str(agg["id"])
        held = await ModuleStore._examples(c, tenant, [module])
        m = operation_mocks.c
        for o in cast(list[dict[str, Any]], agg["operations"]):
            body, name = o.get("stub"), str(o["name"])
            if body is None or body == NO_EXAMPLE or held.get((module, name), NO_EXAMPLE) == body:
                continue
            where = (m.tenant_id == tenant, m.module_id == module, m.operation == name, m.environment == EXAMPLE)
            if (module, name) in held:
                await c.execute(operation_mocks.update().where(*where, m.is_default.is_(True)).values(body=body))
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

    async def all(self, tenant_id: str) -> list[Aggregate]:
        """The modules the acting team reads: its own, workspace-level ones (no team) and those approved for one
        of its workflows, which is the explicit grant across teams. Every module with no acting team."""
        async with self.engine.connect() as c:
            q = (
                tool_modules.select()
                .where(tool_modules.c.tenant_id == tenant_id, sa.or_(team_visible(tool_modules), _granted(tenant_id)))
                .order_by(tool_modules.c.created_at.desc())
            )
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            kids = await self._children(c, tenant_id, [r["id"] for r in rows])
        return [{**r, **kids[r["id"]]} for r in rows]

    async def all_teams(self, tenant_id: str) -> list[Aggregate]:
        """Every team's modules: for what another service asks on a run's behalf (the operations an agent or workflow
        may be granted, a call's resolution), which the run's grants and its approval token decide, not the caller's
        team."""
        async with self.engine.connect() as c:
            q = (
                tool_modules.select()
                .where(tool_modules.c.tenant_id == tenant_id, any_team(tool_modules, RUN_PATHS))
                .order_by(tool_modules.c.created_at.desc())
            )
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            kids = await self._children(c, tenant_id, [r["id"] for r in rows])
        return [{**r, **kids[r["id"]]} for r in rows]

    async def header_holders(self, tenant_id: str | None = None) -> list[Aggregate]:
        """Every team module's operation that carries a header, every tenant's or `tenant_id`'s: its tenant, team,
        module and headers."""
        ops = module_operations.c
        on = sa.and_(ops.tenant_id == tool_modules.c.tenant_id, ops.module_id == tool_modules.c.id)
        q = (
            sa.select(tool_modules.c.tenant_id, tool_modules.c.team_id, ops.module_id, ops.headers)
            .select_from(tool_modules.join(module_operations, on))
            .where(tool_modules.c.team_id.is_not(None), any_team(tool_modules, HEADER_KEYS))
        )
        if tenant_id is not None:
            q = q.where(tool_modules.c.tenant_id == tenant_id)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings() if r["headers"]]

    async def names(self, tenant_id: str, team_id: str | None = None) -> set[str]:
        """Module names of the acting team (or `team_id`), plus workspace-level names: a name is unique per team, so the
        check before a create does not see another team's."""
        with _as_team(team_id):
            q = sa.select(tool_modules.c.name).where(tool_modules.c.tenant_id == tenant_id, team_visible(tool_modules))
            async with self.engine.connect() as c:
                return {str(r[0]) for r in await c.execute(q)}

    async def secret_readers(self, tenant_id: str) -> list[Aggregate]:
        """Each module's id, display name and baseline with its operations' id, name, path and headers: what the
        Secrets page needs to say which operations read a secret, in two reads instead of every child table."""
        ops = module_operations.c
        async with self.engine.connect() as c:
            q = sa.select(tool_modules.c.id, tool_modules.c.display_name, tool_modules.c.baseline).where(
                tool_modules.c.tenant_id == tenant_id, sa.or_(team_visible(tool_modules), _granted(tenant_id))
            )
            rows: dict[str, Aggregate] = {
                r["id"]: {**dict(r), "operations": []} for r in (await c.execute(q)).mappings()
            }
            q = (
                sa.select(ops.module_id, ops.id, ops.name, ops.path, ops.headers)
                .where(ops.tenant_id == tenant_id)
                .order_by(ops.module_id, ops.position)
            )
            for r in (await c.execute(q)).mappings():
                if r["module_id"] in rows:
                    readers: list[dict[str, Any]] = rows[r["module_id"]]["operations"]
                    readers.append(dict(r))
        return list(rows.values())

    async def get(self, tenant_id: str, module_id: str) -> Aggregate | None:
        """The module when the acting team reads it (as `all`); None otherwise, so its routes answer 404."""
        async with self.engine.connect() as c:
            q = tool_modules.select().where(
                tool_modules.c.tenant_id == tenant_id,
                tool_modules.c.id == module_id,
                sa.or_(team_visible(tool_modules), _granted(tenant_id)),
            )
            row = (await c.execute(q)).mappings().first()
            if row is None:
                return None
            return {**dict(row), **(await self._children(c, tenant_id, [module_id]))[module_id]}

    async def get_any(self, tenant_id: str, module_id: str) -> Aggregate | None:
        """The module in any team: for a call's resolution and for a decision agents-service already held to the review
        rules, both authorized by what they carry rather than by the caller's team."""
        async with self.engine.connect() as c:
            q = tool_modules.select().where(
                tool_modules.c.tenant_id == tenant_id, tool_modules.c.id == module_id, any_team(tool_modules, RUN_PATHS)
            )
            row = (await c.execute(q)).mappings().first()
            if row is None:
                return None
            return {**dict(row), **(await self._children(c, tenant_id, [module_id]))[module_id]}

    async def operation_named(
        self, tenant_id: str, name: str, team_id: str | None = None
    ) -> tuple[Aggregate, dict[str, Any]] | None:
        """The module holding operation `name` in the acting team (or `team_id`), and the operation. Another team's
        module of the same name is not seen. A workspace-level module is used when the team has no copy of its own."""
        with _as_team(team_id):
            async with self.engine.connect() as c:
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
                        sa.or_(team_visible(tool_modules), _granted(tenant_id)),
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
                    team_visible(tool_modules),
                )
            )
            async with self.engine.connect() as c:
                return {r[0] for r in await c.execute(q)}

    async def put(
        self,
        agg: Aggregate,
        *,
        expected_revision: int | None,
        seeded: bool = False,
        events: Sequence[dict[str, Any]] = (),
    ) -> Aggregate:
        """Writes the whole aggregate. `expected_revision` None inserts a new module; otherwise the update lands only
        when the stored revision still equals it, else StaleModuleError. Returns the aggregate at its new revision.
        `seeded` writes revision 0, the dev seed's mark for a module nobody has edited. HostNotAllowedError when the
        module names a host the tenant's egress allow-list does not hold; nothing is written then. `events` are
        service events (`outbox.add` keywords) written with the change, so neither commits without the other."""
        # Only the table's columns: a module as a call reaches it carries its connection's address, never stored.
        row = {k: v for k, v in agg.items() if k in tool_modules.c}
        hosts: list[str] = list(dict.fromkeys(agg.get("egress_hosts") or []))
        async with self.engine.begin() as c:
            if hosts:
                listed_q = sa.select(_listed_hosts.c.host).where(
                    _listed_hosts.c.tenant_id == row["tenant_id"], _listed_hosts.c.host.in_(hosts)
                )
                listed = {r[0] for r in await c.execute(listed_q)}
                missing = [h for h in hosts if h not in listed]
                if missing:
                    raise HostNotAllowedError(missing[0])
            if expected_revision is None:
                row["revision"] = 0 if seeded else 1
                await c.execute(tool_modules.insert().values(**row))
            else:
                row["revision"] = 0 if seeded else expected_revision + 1
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
            for key, table in CHILDREN.items():
                # Every row names the same columns (an insert of many rows takes its columns from the first); a
                # seeded or older operation may predate response_transform and timeout_ms, an approval its team.
                # Only the table's own columns: a baseline or staged copy written before a column was dropped
                # (self_approval) still carries it, and a discard writes those copies back.
                rows = [
                    {
                        k: v
                        for k, v in {
                            **CHILD_DEFAULTS.get(key, {}),
                            **r,
                            "tenant_id": row["tenant_id"],
                            "module_id": row["id"],
                            "position": i,
                        }.items()
                        if k in table.c
                    }
                    for i, r in enumerate(agg[key])
                ]
                if rows:
                    await c.execute(table.insert(), rows)
            await self._write_examples(c, agg, row.get("updated_at") or row.get("created_at"))
            if hosts:
                links = [
                    {"tenant_id": row["tenant_id"], "module_id": row["id"], "host": h, "position": i}
                    for i, h in enumerate(hosts)
                ]
                await c.execute(module_egress_hosts.insert(), links)
            for event in events:
                await add_event(c, service_outbox, **event)
        return {**agg, "revision": row["revision"]}

    async def insert_if_missing(self, agg: Aggregate) -> bool:
        """Inserts `agg` as a module nobody has edited (revision 0) unless one with its id is already there, as when two
        first calls race to write it. True when this call wrote it."""
        try:
            await self.put(agg, expected_revision=None, seeded=True)
        except IntegrityError:
            return False
        return True

    async def delete(self, tenant_id: str, module_id: str) -> bool:
        async with self.engine.begin() as c:
            done = await c.execute(
                tool_modules.delete().where(tool_modules.c.tenant_id == tenant_id, tool_modules.c.id == module_id)
            )
            return done.rowcount > 0

    async def count(self, tenant_id: str) -> int:
        q = (
            sa.select(sa.func.count())
            .select_from(tool_modules)
            .where(tool_modules.c.tenant_id == tenant_id, sa.or_(team_visible(tool_modules), _granted(tenant_id)))
        )
        async with self.engine.connect() as c:
            return int((await c.execute(q)).scalar_one())
