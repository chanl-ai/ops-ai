"""The workflow registry's tables and queries: console workflows, their published graphs and validation runs.
`api/workflow_registry.py` compiles graphs, publishes and builds the console's views."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.errors import NotFound
from ops_service_kit.ids import now_iso
from ops_store import Guarantee, isolation
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, team_owned_via
from ops_store.team_scope import any_team, team_visible

from .base import metadata
from .graphs import mine
from .tenancy import OWNER, TOOL_GRANTS, UNIQUE_KEY, RuntimeStore, current_tenant

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


def summary_columns(summary: JsonValue) -> dict[str, int]:
    """The list columns of a test run's summary; a count it does not name is 0."""
    values = summary if isinstance(summary, dict) else {}

    def count(key: str) -> int:
        value = values.get(key)
        return int(value) if isinstance(value, int | float) else 0

    return {
        "passed": count("passed"),
        "total": count("total"),
        "regressions": count("regressions"),
        "checks_failing": count("checksFailing"),
    }


class WorkflowRegistry(RuntimeStore):
    # One version row per (workflow, version), inserted only when missing (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    async def ids(self) -> set[str]:
        """Every row's id, deleted ones included, in every team: a new workflow's id is unique across the workspace."""
        q = sa.select(registry_workflows.c.id).where(
            mine(registry_workflows), any_team(registry_workflows, "a workflow id is unique across every team")
        )
        with isolation.tenant_wide(UNIQUE_KEY):
            async with self.tx() as c:
                return {str(i) for i in (await c.execute(q)).scalars()}

    async def rows(self) -> list[dict[str, Any]]:
        q = (
            sa.select(registry_workflows)
            .where(registry_workflows.c.status != "deleted", mine(registry_workflows), team_visible(registry_workflows))
            .order_by(registry_workflows.c.id)
        )
        async with self.tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def refs_every_team(self) -> list[dict[str, Any]]:
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
                return [dict(r) for r in (await c.execute(q)).mappings()]

    async def owner_team(self, workflow_id: str, conn: AsyncConnection | None = None) -> str | None:
        """The team that owns it, whoever is acting; None when there is none. Only for deciding a refusal by the
        owning team, never for showing the record."""
        return (await self.owner_teams(conn, registry_workflows, {workflow_id}, OWNER)).get(workflow_id)

    async def find(self, workflow_id: str) -> dict[str, Any] | None:
        """The row, deleted or not."""
        q = sa.select(registry_workflows).where(
            registry_workflows.c.id == workflow_id, mine(registry_workflows), team_visible(registry_workflows)
        )
        async with self.tx() as c:
            r = (await c.execute(q)).mappings().first()
        return dict(r) if r else None

    async def row(self, workflow_id: str) -> dict[str, Any]:
        r = await self.find(workflow_id)
        if r is None or r["status"] == "deleted":
            raise NotFound(f"Workflow {workflow_id}")
        return r

    async def versions(self, workflow_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(registry_workflow_versions)
            .where(
                registry_workflow_versions.c.workflow_id == workflow_id,
                mine(registry_workflow_versions),
                team_visible(registry_workflow_versions),
            )
            .order_by(registry_workflow_versions.c.version.desc())
        )
        async with self.tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def create(self, row: dict[str, Any]) -> None:
        async with self.tx() as c:
            await c.execute(registry_workflows.insert().values(**row))

    async def update(self, workflow_id: str, **values: Any) -> None:
        async with self.tx() as c:
            await c.execute(
                registry_workflows.update()
                .where(mine(registry_workflows), registry_workflows.c.id == workflow_id)
                .values(**values, updated_at=now_iso())
            )

    async def add_version(self, row: dict[str, Any]) -> None:
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

    async def save_validation(self, row: dict[str, Any]) -> None:
        async with self.tx() as c:
            await c.execute(registry_validations.insert().values(**row, **summary_columns(row["summary"])))

    async def validations(self, workflow_ids: set[str]) -> list[dict[str, Any]]:
        """Every test run of these workflows, newest first. The ids come from `rows()`: the acting team's."""
        if not workflow_ids:
            return []
        q = (
            sa.select(registry_validations)
            .where(mine(registry_validations), registry_validations.c.workflow_id.in_(sorted(workflow_ids)))
            .order_by(registry_validations.c.ran_at.desc(), registry_validations.c.id.desc())
        )
        async with self.tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def last_validation(self, workflow_id: str) -> dict[str, Any] | None:
        q = (
            sa.select(registry_validations)
            .where(mine(registry_validations), registry_validations.c.workflow_id == workflow_id)
            .order_by(registry_validations.c.ran_at.desc())
            .limit(1)
        )
        async with self.tx() as c:
            r = (await c.execute(q)).mappings().first()
        return dict(r) if r else None
