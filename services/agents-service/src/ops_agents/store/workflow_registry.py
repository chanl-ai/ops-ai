"""The workflow registry's tables and queries: console workflows, their published graphs and validation runs.
`api/workflow_registry.py` compiles graphs, publishes and builds the console's views."""

from __future__ import annotations

from typing import Any, ClassVar, NotRequired, TypedDict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.errors import NotFound
from ops_service_kit.http import Json, JsonList, Out
from ops_service_kit.ids import now_iso
from ops_store import Guarantee, isolation
from ops_store.rows import one, rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, team_owned_via
from ops_store.team_scope import any_team, team_visible

from .base import metadata
from .graphs import mine
from .tenancy import OWNER, TOOL_GRANTS, UNIQUE_KEY, current_tenant
from .versioned import VersionedRegistry

registry_workflows = sa.Table(
    "registry_workflows",
    metadata,
    # The tenant the row belongs to, the caller's on insert, with no default (agents 0109). Leads the
    # key (agents 0108): a seeded workflow's id is chosen, and a tenant whose threads run it holds its own copy.
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("trigger", sa.String(200), nullable=False),
    # draft | live | paused | deleted. A deleted row stays so its id keeps refusing new threads; its graph versions
    # stay for the threads already on them.
    sa.Column("status", sa.String(16), nullable=False),
    # The graph_versions version new threads start on; null until the first publish.
    sa.Column("published_version", sa.Integer),
    sa.Column("draft", sa.JSON),
    sa.Column("draft_saved_at", sa.String(32)),
    sa.Column("draft_saved_by", sa.String(200)),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

registry_workflow_versions = sa.Table(
    "registry_workflow_versions",
    metadata,
    # Its workflow's tenant; the composite key below holds a version to a workflow of the same tenant (agents 0108).
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    sa.Column("workflow_id", sa.String(64), primary_key=True),
    # Same number as the graph_versions row it published.
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("graph", sa.JSON, nullable=False),
    sa.Column("note", sa.Text, nullable=False),
    sa.Column("changes", sa.JSON, nullable=False),
    sa.Column("published_at", sa.String(32), nullable=False),
    sa.Column("published_by", sa.String(200), nullable=False),
    sa.Column("review_id", sa.String(64)),
    sa.ForeignKeyConstraint(
        ["tenant_id", "workflow_id"],
        ["registry_workflows.tenant_id", "registry_workflows.id"],
        name="registry_workflow_versions_tenant_id_workflow_id_fkey",
        ondelete="CASCADE",
        onupdate="CASCADE",
    ),
    info={**TENANT_SCOPED, **team_owned_via("registry_workflows", "workflow_id")},
)

registry_validations = sa.Table(
    "registry_validations",
    metadata,
    # The tenant the row belongs to, the caller's on insert, with no default (agents 0109).
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("workflow_id", sa.String(64), nullable=False, index=True),
    sa.Column("ran_at", sa.String(32), nullable=False),
    sa.Column("target", sa.String(8), nullable=False),
    sa.Column("results", sa.JSON, nullable=False),
    sa.Column("summary", sa.JSON, nullable=False),
    # What the Evals lists read of `summary`, written in the same insert (agents 0117), so they filter and count in SQL.
    sa.Column("passed", sa.Integer, nullable=False),
    sa.Column("total", sa.Integer, nullable=False),
    sa.Column("regressions", sa.Integer, nullable=False),
    sa.Column("checks_failing", sa.Integer, nullable=False),
    info=TENANT_SCOPED,
)


class CheckOutcomeJSON(TypedDict):
    """A compile check's `draft` outcome in a validation result, in reply order."""

    passed: bool
    paused: bool
    toolsCalled: list[str]
    reply: str
    failure: NotRequired[str]


class CheckResultJSON(TypedDict):
    """One compile check as a validation run's result, in reply order."""

    caseId: str
    caseName: str
    draft: CheckOutcomeJSON
    live: None
    regression: bool


class ValidationSummaryJSON(TypedDict):
    """A validation run's `summary`, in reply order."""

    passed: int
    total: int
    regressions: int
    checksFailing: int


class NewValidation(TypedDict):
    """A validation run as the validate route records it, in column order."""

    id: str
    workflow_id: str
    ran_at: str
    target: str
    results: list[CheckResultJSON]
    summary: ValidationSummaryJSON


class NewWorkflow(TypedDict):
    """A registry workflow's columns as a create or a seed writes them, in column order."""

    id: str
    team_id: str
    name: str
    description: str
    trigger: str
    status: str
    published_version: int | None
    draft: Json | None
    draft_saved_at: str | None
    draft_saved_by: str | None
    created_at: str
    updated_at: str


class NewWorkflowVersion(TypedDict):
    """A published version's columns as a publish or a seed writes them, in column order."""

    workflow_id: str
    version: int
    graph: Json
    note: str
    changes: list[str]
    published_at: str
    published_by: str
    review_id: str | None


def summary_columns(summary: ValidationSummaryJSON) -> dict[str, int]:
    """The list columns of a test run's summary; a count it does not name, or names as a non-number, is 0."""

    def count(key: str) -> int:
        value = summary.get(key)
        return int(value) if isinstance(value, int | float) else 0

    return {
        "passed": count("passed"),
        "total": count("total"),
        "regressions": count("regressions"),
        "checks_failing": count("checksFailing"),
    }


class RegistryWorkflowRow(Out):
    """A console workflow: its owning team, status, the graph version new threads start on, and its draft."""

    tenant_id: str
    id: str
    team_id: str
    name: str
    description: str
    trigger: str
    status: str
    published_version: int | None
    draft: Json | None
    draft_saved_at: str | None
    draft_saved_by: str | None
    created_at: str
    updated_at: str


class WorkflowVersionRow(Out):
    """One published version of a workflow: the console graph it was published from and who published it."""

    tenant_id: str
    workflow_id: str
    version: int
    graph: Json
    note: str
    changes: JsonList
    published_at: str
    published_by: str
    review_id: str | None


class ValidationRow(Out):
    """One test run of a workflow: each check's result, the summary, and the summary's counts as columns."""

    tenant_id: str
    id: str
    workflow_id: str
    ran_at: str
    target: str
    results: JsonList
    summary: Json
    passed: int
    total: int
    regressions: int
    checks_failing: int


class WorkflowRegistry(VersionedRegistry[RegistryWorkflowRow, WorkflowVersionRow]):
    # One version row per (workflow, version), inserted only when missing (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})
    head = registry_workflows
    history = registry_workflow_versions
    subject = "workflow_id"
    noun = "Workflow"
    # Keyed by tenant, so each read names the caller's tenant as well as the row policies do, for SQLite.
    in_tenant = True
    head_row = RegistryWorkflowRow
    version_row = WorkflowVersionRow

    async def ids(self) -> set[str]:
        """Every row's id, deleted ones included, in every team: a new workflow's id is unique across the workspace."""
        q = sa.select(registry_workflows.c.id).where(
            mine(registry_workflows), any_team(registry_workflows, "a workflow id is unique across every team")
        )
        with isolation.tenant_wide(UNIQUE_KEY):
            async with self.tx() as c:
                return {str(i) for i in (await c.execute(q)).scalars()}

    async def rows(self) -> list[RegistryWorkflowRow]:
        """The acting team's workflows, deleted ones left out."""
        q = (
            sa.select(registry_workflows)
            .where(registry_workflows.c.status != "deleted", mine(registry_workflows), team_visible(registry_workflows))
            .order_by(registry_workflows.c.id)
        )
        async with self.tx() as c:
            return await rows(c, q, RegistryWorkflowRow)

    async def refs_every_team(self) -> list[RegistryWorkflowRow]:
        """Every team's workflows, for a service that governs calls on their behalf (tools-service checks a grant's
        workflow and team here): what it reads decides access by the workflow's own team, not the caller's."""
        q = (
            sa.select(registry_workflows)
            .where(
                registry_workflows.c.status != "deleted",
                mine(registry_workflows),
                any_team(registry_workflows, "a service checks a workflow's team for a tool grant"),
            )
            .order_by(registry_workflows.c.id)
        )
        with isolation.tenant_wide(TOOL_GRANTS):
            async with self.tx() as c:
                return await rows(c, q, RegistryWorkflowRow)

    async def owner_team(self, workflow_id: str, conn: AsyncConnection | None = None) -> str | None:
        """The team that owns it, whoever is acting; None when there is none. Only for deciding a refusal by the
        owning team, never for showing the record."""
        return (await self.owner_teams(conn, registry_workflows, {workflow_id}, OWNER)).get(workflow_id)

    async def row(self, record_id: str, c: AsyncConnection | None = None, *, lock: bool = False) -> RegistryWorkflowRow:
        """The row, NotFound when it is deleted; `find` returns a deleted one."""
        r = await self.find(record_id, c, lock=lock)
        if r is None or r.status == "deleted":
            raise NotFound(f"Workflow {record_id}")
        return r

    async def create(self, row: NewWorkflow) -> None:
        async with self.tx() as c:
            await c.execute(registry_workflows.insert().values(**row))

    async def update(self, workflow_id: str, **values: Any) -> None:
        async with self.tx() as c:
            await c.execute(
                registry_workflows.update()
                .where(mine(registry_workflows), registry_workflows.c.id == workflow_id)
                .values(**values, updated_at=now_iso())
            )

    async def add_version(self, row: NewWorkflowVersion) -> None:
        async with self.tx() as c:
            exists = (
                await c.execute(
                    sa.select(registry_workflow_versions.c.version).where(
                        mine(registry_workflow_versions),
                        registry_workflow_versions.c.workflow_id == row["workflow_id"],
                        registry_workflow_versions.c.version == row["version"],
                        any_team(registry_workflow_versions, "a version number is unique per workflow"),
                    )
                )
            ).first()
            if exists is None:
                await c.execute(registry_workflow_versions.insert().values(**row))

    async def delete(self, workflow_id: str) -> None:
        await self.row(workflow_id)
        await self.update(workflow_id, status="deleted", draft=None)

    async def save_validation(self, row: NewValidation) -> None:
        async with self.tx() as c:
            await c.execute(registry_validations.insert().values(**row, **summary_columns(row["summary"])))

    async def validations(self, workflow_ids: set[str]) -> list[ValidationRow]:
        """Every test run of these workflows, newest first. The ids come from `rows()`: the acting team's."""
        if not workflow_ids:
            return []
        q = (
            sa.select(registry_validations)
            .where(mine(registry_validations), registry_validations.c.workflow_id.in_(sorted(workflow_ids)))
            .order_by(registry_validations.c.ran_at.desc(), registry_validations.c.id.desc())
        )
        async with self.tx() as c:
            return await rows(c, q, ValidationRow)

    async def last_validation(self, workflow_id: str) -> ValidationRow | None:
        q = (
            sa.select(registry_validations)
            .where(mine(registry_validations), registry_validations.c.workflow_id == workflow_id)
            .order_by(registry_validations.c.ran_at.desc())
            .limit(1)
        )
        async with self.tx() as c:
            return await one(c, q, ValidationRow)
