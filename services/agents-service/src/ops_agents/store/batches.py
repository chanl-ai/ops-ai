"""Batches (c-535): one run of a workflow per row of a CSV or Excel file, started by the workflow worker a few rows a
tick and read back as counts and a table of every row's status and output.

A batch is a record, not a workflow run: Start workflow can start only one fixed workflow, so no single built-in
workflow could start any workflow's rows. Each row keeps its input, its attempt and the run its attempt started; the
run's own status and output are read from `engine_runs` when the page asks. A row's run key is
`batch:<batch>:<row>:<attempt>`, so a tick that loses a race, or a worker that restarts mid-start, adopts the run the
key already names instead of starting a second."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store.tables import engine_runs
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import current_tenant, system_tx, tenant_tx

# The worker reads every tenant's pending rows to start them, then starts each inside its own tenant and team.
BATCH_START = "batch_start"
MAX_ROWS = 500
# A row's run failing with one of these stops its batch: there is no engine spend cap, so the next 499 rows would
# meet the same refusal and spend nothing but a person's time reading them.
BUDGET_CODES = ("budget_exhausted", "key_budget_exhausted", "tenant_budget_exhausted")

run_batches = sa.Table(
    "run_batches",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("workflow_id", sa.String(200), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("mode", sa.String(8), nullable=False),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("file_name", sa.String(300), nullable=False),
    sa.Column("total", sa.Integer, nullable=False),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    # Why the batch stopped starting rows, and when (a model budget refusal); cleared when its failed rows are retried.
    sa.Column("stopped_reason", sa.String(500)),
    sa.Column("stopped_at", sa.String(32)),
    sa.Index("ix_run_batches_workflow", "tenant_id", "workflow_id", "created_at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

run_batch_rows = sa.Table(
    "run_batch_rows",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    sa.Column("batch_id", sa.String(64), primary_key=True),
    # 1-based, as the file's rows are counted after the header.
    sa.Column("row", sa.Integer, primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
    sa.Column("input", sa.JSON, nullable=False),
    # pending until a tick starts its attempt, then started with the run that attempt's key names.
    sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("run_id", sa.String(64)),
    sa.Index("ix_run_batch_rows_pending", "status", "tenant_id", "batch_id", "row"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


def run_key(batch_id: str, row: int, attempt: int) -> str:
    return f"batch:{batch_id}:{row}:{attempt}"


class Batches:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def create(
        self,
        *,
        team_id: str,
        workflow_id: str,
        version: int,
        mode: str,
        file_id: str,
        file_name: str,
        created_by: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        batch = {
            "id": new_id("batch"),
            "team_id": team_id,
            "workflow_id": workflow_id,
            "version": version,
            "mode": mode,
            "file_id": file_id,
            "file_name": file_name,
            "total": len(rows),
            "created_by": created_by,
            "created_at": now_iso(),
        }
        async with tenant_tx(self.engine) as c:
            await c.execute(run_batches.insert().values(**batch))
            await c.execute(
                run_batch_rows.insert(),
                [{"batch_id": batch["id"], "row": i, "team_id": team_id, "input": r} for i, r in enumerate(rows, 1)],
            )
        return batch

    async def get(self, batch_id: str) -> dict[str, Any] | None:
        b = run_batches
        async with tenant_tx(self.engine) as c:
            found = (await c.execute(sa.select(b).where(b.c.id == batch_id, team_visible(b)))).mappings().first()
        return dict(found) if found is not None else None

    async def rows(self, batch_id: str) -> list[dict[str, Any]]:
        """Every row with its run's status, outcome, output and error, failed rows first, then in file order."""
        r, e = run_batch_rows, engine_runs
        joined = r.outerjoin(e, sa.and_(e.c.tenant_id == r.c.tenant_id, e.c.id == r.c.run_id))
        failed_first = sa.case((e.c.status.in_(("failed", "cancelled")), 0), else_=1)
        q = (
            sa.select(
                r.c.row, r.c.attempt, r.c.input, r.c.run_id, r.c.status.label("row_status"),
                e.c.status.label("run_status"), e.c.outcome, e.c.output, e.c.error,
            )
            .select_from(joined)
            .where(r.c.batch_id == batch_id, team_visible(r))
            .order_by(failed_first, r.c.row)
        )  # fmt: skip
        async with tenant_tx(self.engine) as c:
            return [dict(x) for x in (await c.execute(q)).mappings()]

    async def retry_failed(self, batch_id: str) -> int:
        """A new attempt for each row whose run failed or was cancelled; rows that succeeded or are under way stay."""
        r, e, b = run_batch_rows, engine_runs, run_batches
        failed = sa.select(e.c.id).where(e.c.tenant_id == current_tenant(), e.c.status.in_(("failed", "cancelled")))
        async with tenant_tx(self.engine) as c:
            done = await c.execute(
                r.update()
                .where(r.c.batch_id == batch_id, team_visible(r), r.c.run_id.in_(failed))
                .values(attempt=r.c.attempt + 1, status="pending", run_id=None)
            )
            await c.execute(
                b.update().where(b.c.id == batch_id, team_visible(b)).values(stopped_reason=None, stopped_at=None)
            )
        return int(done.rowcount or 0)

    async def pending(self, limit: int) -> list[dict[str, Any]]:
        """Rows waiting for their attempt to start, across every tenant, oldest batch first; none of a stopped batch."""
        r, b = run_batch_rows, run_batches
        q = (
            sa.select(
                r.c.tenant_id, r.c.team_id, r.c.batch_id, r.c.row, r.c.attempt, r.c.input,
                b.c.workflow_id, b.c.version, b.c.mode, b.c.created_by,
            )
            .select_from(r.join(b, sa.and_(b.c.tenant_id == r.c.tenant_id, b.c.id == r.c.batch_id)))
            .where(r.c.status == "pending", b.c.stopped_at.is_(None))
            .order_by(b.c.created_at, r.c.batch_id, r.c.row)
            .limit(limit)
        )  # fmt: skip
        async with system_tx(self.engine, BATCH_START) as c:
            return [dict(x) for x in (await c.execute(q)).mappings()]

    async def spent(self, batch_id: str) -> str | None:
        """The error of a row's run that met the model budget, when one did: the batch stops starting rows."""
        r, e = run_batch_rows, engine_runs
        hit = sa.or_(*(e.c.error.like(f"%{code}%") for code in BUDGET_CODES))
        q = (
            sa.select(e.c.error)
            .select_from(r.join(e, sa.and_(e.c.tenant_id == r.c.tenant_id, e.c.id == r.c.run_id)))
            .where(r.c.batch_id == batch_id, team_visible(r), e.c.status == "failed", hit)
            .limit(1)
        )
        async with tenant_tx(self.engine) as c:
            found = (await c.execute(q)).scalar_one_or_none()
        return str(found) if found is not None else None

    async def stop(self, batch_id: str, reason: str) -> None:
        b = run_batches
        async with tenant_tx(self.engine) as c:
            await c.execute(
                b.update()
                .where(b.c.id == batch_id, team_visible(b), b.c.stopped_at.is_(None))
                .values(stopped_reason=reason[:500], stopped_at=now_iso())
            )

    async def started(self, batch_id: str, row: int, attempt: int, run_id: str) -> None:
        """Names the run a row's attempt started; a later attempt (a retry since) is left as it is."""
        r = run_batch_rows
        async with tenant_tx(self.engine) as c:
            await c.execute(
                r.update()
                .where(r.c.batch_id == batch_id, r.c.row == row, r.c.attempt == attempt, team_visible(r))
                .values(status="started", run_id=run_id)
            )
