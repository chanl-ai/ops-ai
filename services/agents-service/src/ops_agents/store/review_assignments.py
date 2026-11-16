"""Who a Human Task is assigned to: one row per assignment, only ever added, so the latest row per review is
who has it now and the rows before it are the record of who had it. Assigning routes a review to a person; it does not
change who may decide it."""

from __future__ import annotations

from collections.abc import Collection
from typing import ClassVar

import sqlalchemy as sa

from ops_service_kit.http import Out
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import RuntimeStore, current_tenant

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


class AssignmentOut(Out):
    """One assignment as written."""

    id: str
    review_id: str
    assignee: str
    assigned_by: str
    assigned_at: str


IDS_PER_QUERY = 1000


class ReviewAssignments(RuntimeStore):
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    async def assign(self, review_id: str, assignee: str, *, by: str) -> AssignmentOut:
        row = AssignmentOut(
            id=new_id("ras"), review_id=review_id, assignee=assignee, assigned_by=by, assigned_at=now_iso()
        )
        async with self.tx() as c:
            await c.execute(review_assignments.insert().values(**row.model_dump()))
        return row

    async def current(self, review_ids: Collection[str]) -> dict[str, str]:
        """The assignee now of each of `review_ids` that was assigned: its latest assignment, in the caller's tenant.
        Read in queries of at most IDS_PER_QUERY ids, since SQL Server takes at most 2100 parameters a statement."""
        t = review_assignments
        wanted = sorted(set(review_ids))
        out: dict[str, str] = {}
        async with self.tx() as c:
            # One query even for no ids, so a page's statement count does not depend on how many of its tasks are open.
            for i in range(0, len(wanted) or 1, IDS_PER_QUERY):
                # Filtered here as well as by row-level security: SQLite, the tests' and a laptop's store, has none.
                q = (
                    sa.select(t.c.review_id, t.c.assignee)
                    .where(t.c.tenant_id == current_tenant(), t.c.review_id.in_(wanted[i : i + IDS_PER_QUERY]))
                    .order_by(t.c.assigned_at, t.c.id)
                )
                out.update({str(r.review_id): str(r.assignee) for r in (await c.execute(q)).all()})
        return out
