"""The step journal on engine_steps (ops_engine.journal.Journal)."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa

from ops_store import Guarantee

from ..journal import RunCancelledError, StepRow, StepStatus
from .clock import now_iso
from .tables import engine_runs, engine_steps
from .tx import Transactions


class SqlJournal:
    # One row per (run, node, iteration, attempt): a second writer of the same attempt fails on the key (CAS). Each
    # write is checked against the run's lease generation in its own transaction (TRANSACTION), so a superseded
    # worker's step is never recorded.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, tx: Transactions) -> None:
        self.tx = tx

    async def steps(self, run_id: str, node_id: str, iteration: int) -> list[StepRow]:
        t = engine_steps
        q = (
            t.select()
            .where(t.c.run_id == run_id, t.c.node_id == node_id, t.c.iteration == iteration)
            .order_by(t.c.attempt)
        )
        async with self.tx.tenant_tx() as c:
            return [
                StepRow(
                    r.run_id,
                    r.node_id,
                    r.iteration,
                    r.attempt,
                    r.status,
                    r.effects,
                    r.key,
                    input=r.input,
                    port=r.port,
                    output=r.output,
                    error=r.error,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                    node_type=r.node_type,
                )
                for r in (await c.execute(q)).all()
            ]

    async def begin(self, row: StepRow) -> None:
        async with self.tx.tenant_tx() as c:
            await self.tx.check_fence(c, row.run_id, row.generation)
            # Read under the lock a cancel takes (RunStore.cancel), so an attempt either began before the cancel and
            # is recorded when it ends, or does not begin.
            run = engine_runs
            status = (
                await c.execute(sa.select(run.c.status).where(run.c.id == row.run_id).with_for_update(read=True))
            ).scalar()
            if status == "cancelled":
                raise RunCancelledError(f"run {row.run_id} was cancelled before {row.node_id} began")
            await c.execute(
                engine_steps.insert().values(
                    run_id=row.run_id,
                    node_id=row.node_id,
                    iteration=row.iteration,
                    attempt=row.attempt,
                    tenant_id=self.tx.tenant(),
                    status=row.status,
                    effects=row.effects,
                    key=row.key,
                    input=row.input,
                    started_at=now_iso(),
                    node_type=row.node_type,
                )
            )

    async def finish(
        self, row: StepRow, *, status: StepStatus, port: str | None, output: Any, error: str | None
    ) -> None:
        t = engine_steps
        async with self.tx.tenant_tx() as c:
            await self.tx.check_fence(c, row.run_id, row.generation)
            await c.execute(
                t.update()
                .where(
                    t.c.run_id == row.run_id,
                    t.c.node_id == row.node_id,
                    t.c.iteration == row.iteration,
                    t.c.attempt == row.attempt,
                )
                .values(status=status, port=port, output=output, error=error, finished_at=now_iso())
            )
