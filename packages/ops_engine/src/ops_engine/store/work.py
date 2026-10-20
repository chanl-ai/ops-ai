"""The work queue on engine_work. A worker claims one row at a time past row-level security (it does not know the
tenant yet), with FOR UPDATE SKIP LOCKED so two workers never take one row, then does the work under the row's tenant.
A claim lasts `ttl` seconds unless renewed; a dead worker's claim lapses and the row is claimed again with its
attempt count raised. PostgreSQL only, as the timers' poller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_store import Guarantee

from .clock import db_now, now_iso
from .tables import ENGINE_BUILD, engine_work
from .tx import CLAIM_WORK, Transactions


@dataclass(frozen=True)
class Work:
    id: int
    tenant_id: str
    run_id: str
    kind: str
    payload: Any
    attempts: int
    claimed_by: str


class WorkQueue:
    # SKIP LOCKED claims (LOCK), expiry by the database's clock (CLOCK), one row per dedupe key (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.LOCK, Guarantee.CLOCK, Guarantee.CAS})

    def __init__(self, tx: Transactions, owner: str, ttl: float, build: str = ENGINE_BUILD) -> None:
        self.tx, self.owner, self.ttl, self.build = tx, owner, ttl, build

    async def claim(self) -> Work | None:
        w = engine_work
        async with self.tx.system_tx(CLAIM_WORK) as c:
            now = db_now(c)
            due = sa.or_(
                sa.and_(w.c.status == "queued", w.c.available_at <= now),
                sa.and_(w.c.status == "claimed", w.c.lease_expires_at < now),
            )
            q = (
                sa.select(w.c.id)
                .where(due, w.c.build == self.build)
                .order_by(w.c.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            found = (await c.execute(q)).scalar_one_or_none()
            if found is None:
                return None
            row = (
                await c.execute(
                    w.update()
                    .where(w.c.id == found)
                    .values(
                        status="claimed",
                        claimed_by=self.owner,
                        lease_expires_at=now + self.ttl,
                        attempts=w.c.attempts + 1,
                    )
                    .returning(w.c.id, w.c.tenant_id, w.c.run_id, w.c.kind, w.c.payload, w.c.attempts, w.c.claimed_by)
                )
            ).one()
        return Work(int(row.id), row.tenant_id, row.run_id, row.kind, row.payload, int(row.attempts), row.claimed_by)

    async def renew(self, work: Work) -> bool:
        """Extends this worker's claim; False when it has lapsed and another worker took the row."""
        w = engine_work
        async with self.tx.tenant_tx() as c:
            res = await c.execute(
                w.update()
                .where(w.c.id == work.id, w.c.claimed_by == self.owner, w.c.status == "claimed")
                .values(lease_expires_at=db_now(c) + self.ttl)
            )
            return res.rowcount == 1

    async def done(self, work: Work, *, status: str = "done", error: str | None = None) -> None:
        w = engine_work
        async with self.tx.tenant_tx() as c:
            await c.execute(
                w.update()
                .where(w.c.id == work.id, w.c.claimed_by == self.owner)
                .values(status=status, error=error, lease_expires_at=None)
            )

    async def release(self, work: Work, delay: float, *, error: str | None = None) -> None:
        """Back to the queue after `delay` seconds: the run's lease was busy, or the attempt failed and may retry."""
        w = engine_work
        async with self.tx.tenant_tx() as c:
            await c.execute(
                w.update()
                .where(w.c.id == work.id, w.c.claimed_by == self.owner)
                .values(status="queued", available_at=db_now(c) + delay, lease_expires_at=None, error=error)
            )

    async def enqueue(
        self, run_id: str, kind: str, dedupe_key: str, payload: Any = None, *, after_seconds: float = 0.0
    ) -> tuple[dict[str, Any], bool]:
        """Adds a row, or returns the one already written under `dedupe_key`. Returns (row, created). `after_seconds`
        holds the row back until then on the database's clock: a review's deadline."""
        w = engine_work
        try:
            async with self.tx.tenant_tx() as c:
                await c.execute(
                    w.insert().values(
                        tenant_id=self.tx.tenant(),
                        run_id=run_id,
                        kind=kind,
                        payload=payload,
                        dedupe_key=dedupe_key,
                        status="queued",
                        build=self.build,
                        available_at=db_now(c) + after_seconds,
                        attempts=0,
                        created_at=now_iso(),
                    )
                )
            created = True
        except IntegrityError:
            created = False
        async with self.tx.tenant_tx() as c:
            row = (
                (await c.execute(w.select().where(w.c.tenant_id == self.tx.tenant(), w.c.dedupe_key == dedupe_key)))
                .mappings()
                .one()
            )
        return dict(row), created
