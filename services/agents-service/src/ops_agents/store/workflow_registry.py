"""The workflow registry's tables and queries: console workflows, their published graphs and validation runs.
`api/workflow_registry.py` compiles graphs, publishes and builds the console's views."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.errors import NotFound
from ops_service_kit.ids import now_iso
from ops_store import Guarantee

from .base import metadata

registry_workflows = sa.Table(
    "registry_workflows",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("owner", sa.String(200), nullable=False),
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
)

registry_workflow_versions = sa.Table(
    "registry_workflow_versions",
    metadata,
    sa.Column(
        "workflow_id", sa.String(64), sa.ForeignKey("registry_workflows.id", ondelete="CASCADE"), primary_key=True
    ),
    # Same number as the graph_versions row it published.
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("graph", sa.JSON, nullable=False),
    sa.Column("note", sa.Text, nullable=False),
    sa.Column("changes", sa.JSON, nullable=False),
    sa.Column("published_at", sa.String(32), nullable=False),
    sa.Column("published_by", sa.String(200), nullable=False),
    sa.Column("review_id", sa.String(64)),
)

registry_validations = sa.Table(
    "registry_validations",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("workflow_id", sa.String(64), nullable=False, index=True),
    sa.Column("ran_at", sa.String(32), nullable=False),
    sa.Column("target", sa.String(8), nullable=False),
    sa.Column("results", sa.JSON, nullable=False),
    sa.Column("summary", sa.JSON, nullable=False),
)


class WorkflowRegistry:
    # One version row per (workflow, version), inserted only when missing (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def ids(self) -> set[str]:
        """Every row's id, deleted ones included."""
        async with self.engine.connect() as c:
            return {str(i) for i in (await c.execute(sa.select(registry_workflows.c.id))).scalars()}

    async def rows(self) -> list[dict[str, Any]]:
        q = sa.select(registry_workflows).where(registry_workflows.c.status != "deleted")
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def find(self, workflow_id: str) -> dict[str, Any] | None:
        """The row, deleted or not."""
        q = sa.select(registry_workflows).where(registry_workflows.c.id == workflow_id)
        async with self.engine.connect() as c:
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
            .where(registry_workflow_versions.c.workflow_id == workflow_id)
            .order_by(registry_workflow_versions.c.version.desc())
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def create(self, row: dict[str, Any]) -> None:
        async with self.engine.begin() as c:
            await c.execute(registry_workflows.insert().values(**row))

    async def update(self, workflow_id: str, **values: Any) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                registry_workflows.update()
                .where(registry_workflows.c.id == workflow_id)
                .values(**values, updated_at=now_iso())
            )

    async def add_version(self, row: dict[str, Any]) -> None:
        async with self.engine.begin() as c:
            exists = (
                await c.execute(
                    sa.select(registry_workflow_versions.c.version).where(
                        registry_workflow_versions.c.workflow_id == row["workflow_id"],
                        registry_workflow_versions.c.version == row["version"],
                    )
                )
            ).first()
            if exists is None:
                await c.execute(registry_workflow_versions.insert().values(**row))

    async def delete(self, workflow_id: str) -> None:
        await self.row(workflow_id)
        await self.update(workflow_id, status="deleted", draft=None)

    async def save_validation(self, row: dict[str, Any]) -> None:
        async with self.engine.begin() as c:
            await c.execute(registry_validations.insert().values(**row))

    async def last_validation(self, workflow_id: str) -> dict[str, Any] | None:
        q = (
            sa.select(registry_validations)
            .where(registry_validations.c.workflow_id == workflow_id)
            .order_by(registry_validations.c.ran_at.desc())
            .limit(1)
        )
        async with self.engine.connect() as c:
            r = (await c.execute(q)).mappings().first()
        return dict(r) if r else None
