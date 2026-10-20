"""Who a Human Task is assigned to (c-074): one row per assignment, only ever added, so the latest row per review is
who has it now and the rows before it are the record of who had it. Assigning routes a review to a person; it does not
change who may decide it."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import current_tenant, tenant_tx

review_assignments = sa.Table(
    "review_assignments",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    # A review's id as Human Tasks lists it: a runner step (wfrun_…:node:n), a thread, or a publish request.
    sa.Column("review_id", sa.String(200), nullable=False),
    sa.Column("assignee", sa.String(320), nullable=False),
    sa.Column("assigned_by", sa.String(320), nullable=False),
    sa.Column("assigned_at", sa.String(32), nullable=False),
    sa.Index("ix_review_assignments_review", "tenant_id", "review_id", "assigned_at"),
    info=TENANT_SCOPED,
)


class ReviewAssignments:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def assign(self, review_id: str, assignee: str, *, by: str) -> dict[str, Any]:
        row = {
            "id": new_id("ras"),
            "review_id": review_id,
            "assignee": assignee,
            "assigned_by": by,
            "assigned_at": now_iso(),
        }
        async with tenant_tx(self.engine) as c:
            await c.execute(review_assignments.insert().values(**row))
        return row

    async def current(self) -> dict[str, str]:
        """Each assigned review's assignee now: the latest assignment of each, in the caller's tenant."""
        t = review_assignments
        async with tenant_tx(self.engine) as c:
            # Filtered here as well as by row-level security: SQLite, the tests' and a laptop's store, has none.
            q = (
                sa.select(t.c.review_id, t.c.assignee)
                .where(t.c.tenant_id == current_tenant())
                .order_by(t.c.assigned_at, t.c.id)
            )
            return {str(r.review_id): str(r.assignee) for r in (await c.execute(q)).all()}
