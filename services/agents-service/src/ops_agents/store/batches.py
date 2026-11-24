"""Batches: one run of a workflow per row of a CSV or Excel file, started by the workflow worker a few rows a
tick and read back as counts and a table of every row's status and output.

A batch is a record, not a workflow run: Start workflow can start only one fixed workflow, so no single built-in
workflow could start any workflow's rows. Each row keeps its input, its attempt and the run its attempt started; the
run's own status and output are read from `engine_runs` when the page asks. A row's run key is
`batch:<batch>:<row>:<attempt>`, so a tick that loses a race, or a worker that restarts mid-start, adopts the run the
key already names instead of starting a second."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_engine.store.tables import engine_runs
from ops_service_kit.http import Json, ListPage, Out
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.dialect import locked
from ops_store.listing import LISTED, list_page
from ops_store.rows import one, rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import RuntimeStore, current_tenant

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
    # upload: rows of a spreadsheet; check: the new and changed files of one check of a watched folder.
    sa.Column("origin", sa.String(8), nullable=False, server_default="upload"),
    # The spreadsheet's file; null for a check, which names its watch instead.
    sa.Column("file_id", sa.String(64)),
    # The spreadsheet's name, or a check's label (its watch and check time).
    sa.Column("file_name", sa.String(300), nullable=False),
    sa.Column("watch_id", sa.String(64)),
    sa.Column("checked_at", sa.String(32)),
    sa.Column("total", sa.Integer, nullable=False),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False, info=LISTED),
    # Why the batch stopped starting rows, and when (a model budget refusal); cleared when its failed rows are retried.
    sa.Column("stopped_reason", sa.String(500)),
    sa.Column("stopped_at", sa.String(32)),
    # The group a check's files were split into (Group by): a digest of its name, the name and its named parts, and
    # the part, 2 onward once a group passes MAX_ROWS rows. Every other batch is its own group, keyed by its id.
    sa.Column("group_key", sa.String(96), nullable=False),
    sa.Column("group_name", sa.String(300)),
    sa.Column("group_parts", sa.JSON),
    sa.Column("part", sa.Integer, nullable=False, server_default="1"),
    sa.Index("ix_run_batches_workflow", "tenant_id", "workflow_id", "created_at"),
    # One batch per group part per workflow: two checks that find a group's files at once add to one batch.
    sa.Index("ux_run_batches_group", "tenant_id", "workflow_id", "group_key", "part", unique=True),
    # The batch list sorts on created_at (the listing gate's index, after the tenant and team every read names).
    sa.Index("ix_run_batches_created", "tenant_id", "team_id", "created_at"),
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
    sa.Column("workflow_id", sa.String(200), nullable=False),
    # What the row stands for: `<batch>:<row>` for a spreadsheet row, a digest of `<file>:<version>` for a check's
    # file version, so one version is one row per workflow however many checks read it.
    sa.Column("item_key", sa.String(96), nullable=False),
    sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
    sa.Column("input", sa.JSON, nullable=False),
    # pending until a tick starts its attempt, then started with the run that attempt's key names. removed and
    # failed (a file removed at the source, or one too large) are written so and never started.
    sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("run_id", sa.String(64)),
    sa.Column("failure_code", sa.String(32)),
    sa.Column("reason", sa.String(500)),
    sa.Index("ix_run_batch_rows_pending", "status", "tenant_id", "batch_id", "row"),
    # One row per file version per workflow: two collectors of one check, or two overlapping checks, cannot both
    # write it.
    sa.Index("ux_run_batch_rows_item", "tenant_id", "workflow_id", "item_key", unique=True),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class BatchOut(Out):
    """One batch: what was started from which file, and why it stopped starting rows when it did."""

    id: str
    team_id: str
    workflow_id: str
    version: int
    mode: str
    origin: str = "upload"
    file_id: str | None
    file_name: str
    watch_id: str | None = None
    checked_at: str | None = None
    total: int
    created_by: str
    created_at: str
    stopped_reason: str | None = None
    stopped_at: str | None = None
    group_key: str | None = None
    group_name: str | None = None
    group_parts: Json | None = None
    part: int = 1


class BatchRowOut(Out):
    """One row of a batch with its run's status, outcome, output and error (all None before its run starts)."""

    row: int
    attempt: int
    input: Json
    run_id: str | None
    row_status: str
    run_status: str | None
    outcome: str | None
    output: Any
    error: str | None
    failure_code: str | None = None
    reason: str | None = None


class PendingRowOut(Out):
    """A row waiting for its attempt to start, with what the worker starts it as."""

    tenant_id: str
    team_id: str
    batch_id: str
    row: int
    attempt: int
    input: Json
    workflow_id: str
    version: int
    mode: Literal["live", "test"]
    created_by: str


_b = run_batches.c
BATCH_COLUMNS = (
    _b.id, _b.team_id, _b.workflow_id, _b.version, _b.mode, _b.origin, _b.file_id, _b.file_name, _b.watch_id,
    _b.checked_at, _b.total, _b.created_by, _b.created_at, _b.stopped_reason, _b.stopped_at, _b.group_key,
    _b.group_name, _b.group_parts, _b.part,
)  # fmt: skip


def run_key(batch_id: str, row: int, attempt: int) -> str:
    return f"batch:{batch_id}:{row}:{attempt}"


class Batches(RuntimeStore):
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

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
        rows: list[Json],
    ) -> BatchOut:
        batch_id = new_id("batch")
        batch = {
            "id": batch_id,
            "group_key": batch_id,
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
        async with self.tx() as c:
            await c.execute(run_batches.insert().values(**batch))
            await c.execute(
                run_batch_rows.insert(),
                [
                    {
                        "batch_id": batch["id"],
                        "row": i,
                        "team_id": team_id,
                        "workflow_id": workflow_id,
                        "item_key": f"{batch['id']}:{i}",
                        "input": r,
                    }
                    for i, r in enumerate(rows, 1)
                ],
            )
        return BatchOut.model_validate(batch)

    async def open_group(
        self,
        *,
        team_id: str,
        workflow_id: str,
        version: int,
        mode: str,
        watch_id: str,
        checked_at: str,
        group_key: str,
        group_name: str,
        group_parts: Json | None,
        created_by: str,
    ) -> BatchOut:
        """The group's batch with room for another row: its newest part while that holds fewer than MAX_ROWS rows,
        else the next part, made here. A part another check made at the same moment is read, not made twice."""
        b = run_batches
        newest = (
            sa.select(*BATCH_COLUMNS)
            .where(b.c.tenant_id == current_tenant(), b.c.workflow_id == workflow_id, b.c.group_key == group_key)
            .order_by(b.c.part.desc())
            .limit(1)
        )
        for _ in range(3):
            async with self.tx() as c:
                found = await one(c, newest, BatchOut)
            if found is not None and found.total < MAX_ROWS:
                return found
            batch = {
                "id": new_id("batch"),
                "team_id": team_id,
                "workflow_id": workflow_id,
                "version": version,
                "mode": mode,
                "origin": "check",
                "file_id": None,
                "file_name": group_name if found is None else f"{group_name} (part {found.part + 1})",
                "watch_id": watch_id,
                "checked_at": checked_at,
                "total": 0,
                "created_by": created_by,
                "created_at": now_iso(),
                "group_key": group_key,
                "group_name": group_name,
                "group_parts": group_parts,
                "part": 1 if found is None else found.part + 1,
            }
            try:
                async with self.tx() as c:
                    await c.execute(b.insert().values(**batch))
            except IntegrityError:
                continue
            return BatchOut.model_validate(batch)
        raise RuntimeError(f"Group {group_key} of {workflow_id} could not be opened: every attempt lost a race.")

    async def add_rows(self, batch_id: str, rows_in: list[Json]) -> tuple[int, list[Json]]:
        """Adds rows (`{itemKey, input, status?, failureCode?, reason?}`) after the batch's last row, as many as it
        has room for, and raises its total in the same transaction. A row whose item the workflow already holds is
        skipped. Answers the number added and the rows left for the next part."""
        b, r = run_batches, run_batch_rows
        async with self.tx() as c:
            mine = sa.select(b.c.team_id, b.c.workflow_id, b.c.total).where(
                b.c.tenant_id == current_tenant(), b.c.id == batch_id, team_visible(b)
            )
            found = (await c.execute(locked(cast(sa.Select[Any], mine), b))).mappings().first()
            if found is None:
                raise KeyError(batch_id)
            keys = [str(x["itemKey"]) for x in rows_in]
            held = set(
                (await c.execute(sa.select(r.c.item_key).where(
                    r.c.tenant_id == current_tenant(), r.c.workflow_id == found["workflow_id"], r.c.item_key.in_(keys)
                ))).scalars()
            )  # fmt: skip
            fresh = [x for x in rows_in if str(x["itemKey"]) not in held]
            room = max(MAX_ROWS - int(found["total"]), 0)
            taking, left = fresh[:room], fresh[room:]
            last = (await c.execute(sa.select(sa.func.max(r.c.row)).where(
                r.c.tenant_id == current_tenant(), r.c.batch_id == batch_id
            ))).scalar() or 0  # fmt: skip
            if taking:
                await c.execute(
                    r.insert(),
                    [
                        {
                            "batch_id": batch_id,
                            "row": last + i,
                            "team_id": found["team_id"],
                            "workflow_id": found["workflow_id"],
                            "item_key": str(x["itemKey"]),
                            "input": x["input"],
                            "status": str(x.get("status") or "pending"),
                            "failure_code": x.get("failureCode"),
                            "reason": x.get("reason"),
                        }
                        for i, x in enumerate(taking, 1)
                    ],
                )
                await c.execute(
                    sa.update(b).where(b.c.tenant_id == current_tenant(), b.c.id == batch_id)
                    .values(total=b.c.total + len(taking))
                )  # fmt: skip
        return len(taking), left

    async def get(self, batch_id: str) -> BatchOut | None:
        async with self.tx() as c:
            return await one(c, sa.select(*BATCH_COLUMNS).where(_b.id == batch_id, team_visible(run_batches)), BatchOut)

    async def of_workflow(self, workflow_id: str, params: ListParams) -> ListPage:
        """One page of the workflow's batches, newest first, each with its rows counted in SQL by where they stand: a
        row with no run is pending, unless it was written removed or failed (a check's file that never ran)."""
        r, e, b = run_batch_rows, engine_runs, run_batches
        run, mine = e.c.status, r.c.status

        def count(cond: sa.ColumnElement[bool], name: str) -> sa.Label[Any]:
            return sa.func.coalesce(sa.func.sum(sa.case((cond, 1), else_=0)), 0).label(name)

        no_run = run.is_(None)
        counts = (
            sa.select(
                r.c.tenant_id, r.c.batch_id,
                count(run == "succeeded", "finished"),
                count(run == "waiting", "waiting"),
                count(sa.or_(run.in_(("failed", "cancelled")), sa.and_(no_run, mine == "failed")), "failed"),
                count(sa.and_(no_run, mine == "removed"), "removed"),
                count(sa.and_(no_run, mine.not_in(("failed", "removed"))), "pending"),
                count(run.not_in(("succeeded", "failed", "cancelled", "waiting")), "running"),
            )
            .select_from(r.outerjoin(e, sa.and_(e.c.tenant_id == r.c.tenant_id, e.c.id == r.c.run_id)))
            .where(r.c.tenant_id == current_tenant(), team_visible(r))
            .group_by(r.c.tenant_id, r.c.batch_id)
            .subquery()
        )  # fmt: skip
        n = counts.c
        q = (
            sa.select(
                *BATCH_COLUMNS,
                *(sa.func.coalesce(col, 0).label(col.name) for col in
                  (n.finished, n.waiting, n.failed, n.removed, n.pending, n.running)),
            )
            .select_from(b.outerjoin(counts, sa.and_(n.tenant_id == b.c.tenant_id, n.batch_id == b.c.id)))
            .where(b.c.tenant_id == current_tenant(), b.c.workflow_id == workflow_id, team_visible(b))
        )  # fmt: skip
        async with self.tx() as c:
            return await list_page(
                c, q, params, sortable={"createdAt": b.c.created_at}, default_sort=b.c.created_at.desc()
            )

    async def rows(self, batch_id: str) -> list[BatchRowOut]:
        """Every row with its run's status, outcome, output and error, failed rows first, then in file order."""
        r, e = run_batch_rows, engine_runs
        joined = r.outerjoin(e, sa.and_(e.c.tenant_id == r.c.tenant_id, e.c.id == r.c.run_id))
        # Rows that never ran (a file too large, removed at the source) sort with the failed ones.
        failed_first = sa.case(
            (e.c.status.in_(("failed", "cancelled")), 0), (r.c.status.in_(("failed", "removed")), 0), else_=1
        )
        q = (
            sa.select(
                r.c.row, r.c.attempt, r.c.input, r.c.run_id, r.c.status.label("row_status"),
                e.c.status.label("run_status"), e.c.outcome, e.c.output, e.c.error, r.c.failure_code, r.c.reason,
            )
            .select_from(joined)
            .where(r.c.batch_id == batch_id, team_visible(r))
            .order_by(failed_first, r.c.row)
        )  # fmt: skip
        async with self.tx() as c:
            return await rows(c, q, BatchRowOut)

    async def retry_failed(self, batch_id: str) -> tuple[int, int]:
        """A new attempt for each row whose run failed or was cancelled; rows that succeeded or are under way stay.
        Rows that never ran (a check's file removed at the source or refused) have no run to start again: they are
        left and counted. Answers (retried, not retryable)."""
        r, e, b = run_batch_rows, engine_runs, run_batches
        failed = sa.select(e.c.id).where(e.c.tenant_id == current_tenant(), e.c.status.in_(("failed", "cancelled")))
        never_ran = sa.select(sa.func.count()).where(
            r.c.batch_id == batch_id, team_visible(r), r.c.run_id.is_(None), r.c.status.in_(("failed", "removed"))
        )
        async with self.tx() as c:
            left = int((await c.execute(never_ran)).scalar_one())
            done = await c.execute(
                r.update()
                .where(r.c.batch_id == batch_id, team_visible(r), r.c.run_id.in_(failed))
                .values(attempt=r.c.attempt + 1, status="pending", run_id=None)
            )
            await c.execute(
                b.update().where(b.c.id == batch_id, team_visible(b)).values(stopped_reason=None, stopped_at=None)
            )
        return int(done.rowcount or 0), left

    async def pending(self, limit: int) -> list[PendingRowOut]:
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
        async with self.system_tx(BATCH_START) as c:
            return await rows(c, q, PendingRowOut)

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
        async with self.tx() as c:
            found = (await c.execute(q)).scalar_one_or_none()
        return str(found) if found is not None else None

    async def stop(self, batch_id: str, reason: str) -> None:
        b = run_batches
        async with self.tx() as c:
            await c.execute(
                b.update()
                .where(b.c.id == batch_id, team_visible(b), b.c.stopped_at.is_(None))
                .values(stopped_reason=reason[:500], stopped_at=now_iso())
            )

    async def started(self, batch_id: str, row: int, attempt: int, run_id: str) -> None:
        """Names the run a row's attempt started; a later attempt (a retry since) is left as it is."""
        r = run_batch_rows
        async with self.tx() as c:
            await c.execute(
                r.update()
                .where(r.c.batch_id == batch_id, r.c.row == row, r.c.attempt == attempt, team_visible(r))
                .values(status="started", run_id=run_id)
            )
