"""The work queue on engine_work. A worker claims one row at a time past row-level security (it does not know the
tenant yet), skipping rows another worker holds (SKIP LOCKED on PostgreSQL, READPAST on SQL Server, `ops_store.dialect`)
so two workers never take one row, then does the work under the row's tenant. A claim lasts `ttl` seconds unless
renewed; a dead worker's claim lapses and the row is claimed again with its attempt count raised.

Fair claim (workflow-runner.md section 5). Each row carries its run's team, a priority and a concurrency key (the team
when none is set). With `team_cap` set, a key whose rows already run on `team_cap` live claims is skipped, so one
team at its cap never holds back another, and among the rest the oldest row of the highest priority goes first, read
in the order of one index (ix_engine_work_claim) rather than sorted per claim. Only claimed rows with a live lease
count; a run waiting for a person, an event or a timer has no claimed row and takes no slot. The cap is exact: the
last check runs under a lock on the key (`ops_store.dialect.lock_key`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_service_kit.http import Json
from ops_store import Guarantee
from ops_store.dialect import claim as claim_rows
from ops_store.dialect import lock_key

from .clock import db_now, now_iso
from .tables import ENGINE_BUILD, engine_runs, engine_work
from .tx import CLAIM_WORK, Transactions

# A row whose claim lapsed more often than this is not claimed again: its run kills the worker that takes it, and the
# run reconciler marks it Stuck with that reason.
MAX_LAPSES = 5
# Keys a claim passes over when each fills while it waits for its lock, before it gives up until the next poll.
CAP_TRIES = 3
# Rows a claim reads before it locks one; another claim holding them all at once is what makes it come back empty.
CANDIDATES = 16


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

    def __init__(
        self, tx: Transactions, owner: str, ttl: float, build: str = ENGINE_BUILD, *, team_cap: int | None = None
    ) -> None:
        self.tx, self.owner, self.ttl, self.build, self.team_cap = tx, owner, ttl, build, team_cap

    async def claim(self) -> Work | None:
        w = engine_work
        async with self.tx.system_tx(CLAIM_WORK) as c:
            now = db_now(c)
            due = sa.or_(
                sa.and_(w.c.status == "queued", w.c.available_at <= now),
                sa.and_(w.c.status == "claimed", w.c.lease_expires_at < now),
            )
            # Read in ix_engine_work_claim's order, so the claim stops at the first row it may take.
            q = (
                cast(sa.Select[Any], sa.select(w.c.id, w.c.tenant_id, _key(w).label("key")))
                .where(due, w.c.build == self.build, w.c.lapses <= MAX_LAPSES)
                .order_by(w.c.priority.desc(), w.c.id)
            )
            full: list[tuple[str, str]] = []
            for _ in range(CAP_TRIES):
                found = await self._first(c, q, now, full)
                if found is None:
                    return None
                if self.team_cap is None:
                    break
                # Two workers can each read the key one under its cap; the second waits here and reads the first's.
                await lock_key(c, f"engine_work_cap:{found.tenant_id}:{found.key}")
                held = self._running(now, found.tenant_id, found.key)
                if not any(int(r.n) >= self.team_cap for r in (await c.execute(held)).all()):
                    break
                # That key filled while this claim waited: the next key under its cap is taken instead.
                full.append((found.tenant_id, found.key))
            else:
                return None
            row = (
                await c.execute(
                    w.update()
                    .where(w.c.id == found.id)
                    .values(
                        status="claimed",
                        claimed_by=self.owner,
                        lease_expires_at=now + self.ttl,
                        attempts=w.c.attempts + 1,
                        # Still claimed when taken again: its worker died with the claim, not gave it back.
                        lapses=w.c.lapses + sa.case((w.c.status == "claimed", 1), else_=0),
                    )
                    .returning(w.c.id, w.c.tenant_id, w.c.run_id, w.c.kind, w.c.payload, w.c.attempts, w.c.claimed_by)
                )
            ).one()
        return Work(int(row.id), row.tenant_id, row.run_id, row.kind, row.payload, int(row.attempts), row.claimed_by)

    async def _first(self, c: Any, q: sa.Select[Any], now: Any, full: list[tuple[str, str]]) -> Any:
        """The first row of `q` this claim may take, locked: with a cap, one whose key is under it and not in
        `full`. The first CANDIDATES ids are read without a lock, and only they are locked: SQL Server keeps an
        update lock on every row a locking read touches, so one claim reading every due row would hold them all and a
        second claim (READPAST) would find none."""
        w = engine_work
        if self.team_cap is not None:
            running = self._running(now).subquery("running")
            q = q.select_from(
                w.outerjoin(running, sa.and_(running.c.tenant_id == w.c.tenant_id, running.c.key == _key(w)))
            ).where(sa.func.coalesce(running.c.n, 0) < self.team_cap)
            for tenant, key in full:
                q = q.where(sa.not_(sa.and_(w.c.tenant_id == tenant, _key(w) == key)))
        for _ in range(CAP_TRIES):
            ids = (await c.execute(q.with_only_columns(w.c.id).limit(CANDIDATES))).scalars().all()
            if not ids:
                return None
            first = q.where(w.c.id.in_(ids)).limit(1)
            if (found := (await c.execute(claim_rows(first, w))).one_or_none()) is not None:
                return found
            # Every candidate was taken, or its key filled, since they were read: read the next ones.
        return None

    def _running(self, now: Any, tenant: str | None = None, key: str | None = None) -> sa.Select[Any]:
        """Live claims per tenant and key: what the cap counts. A lapsed claim's worker is gone, so it is not
        counted."""
        b = engine_work.alias("busy")
        q = cast(
            sa.Select[Any],
            sa.select(b.c.tenant_id, _key(b).label("key"), sa.func.count().label("n")).where(
                b.c.status == "claimed", b.c.lease_expires_at >= now, b.c.build == self.build
            ),
        )
        if tenant is not None and key is not None:
            q = q.where(b.c.tenant_id == tenant, _key(b) == key)
        return q.group_by(b.c.tenant_id, _key(b))

    async def due(self) -> int:
        """How many rows wait to be claimed now, for the workflow worker's heartbeat."""
        w = engine_work
        async with self.tx.system_tx(CLAIM_WORK) as c:
            now = db_now(c)
            q = (
                sa.select(sa.func.count())
                .select_from(w)
                .where(w.c.status == "queued", w.c.available_at <= now, w.c.build == self.build)
            )
            return int((await c.execute(q)).scalar_one() or 0)

    async def leaving(self, run_id: str, interrupt_id: str, node: str, iteration: int) -> bool:
        """Whether the run's pause is already being left: a decision or callback queued for it, or its time limit due.
        Rows are claimed oldest first, so a reminder queued before the decision is claimed before it."""
        w = engine_work
        async with self.tx.tenant_tx() as c:
            now = db_now(c)
            q = sa.select(w.c.kind, w.c.payload).where(
                w.c.run_id == run_id,
                w.c.status.in_(("queued", "claimed")),
                sa.or_(w.c.kind == "resume", sa.and_(w.c.kind == "timeout", w.c.available_at <= now)),
            )
            rows = (await c.execute(q)).all()
        for r in rows:
            p = cast(Json, r.payload or {})
            if r.kind == "resume" and p.get("interruptId") in (None, interrupt_id):
                return True
            if r.kind == "timeout" and (p.get("node"), p.get("iteration")) == (node, iteration):
                return True
        return False

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
                        priority=0,
                        created_at=now_iso(),
                        # The run's team, read in the same statement, so no caller has to name it.
                        team_id=sa.select(engine_runs.c.team_id)
                        .where(engine_runs.c.tenant_id == self.tx.tenant(), engine_runs.c.id == run_id)
                        .scalar_subquery(),
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


def _key(t: sa.FromClause) -> sa.ColumnElement[str]:
    """The key a row's cap counts: its concurrency key, else its team (agents migration 0124 filled it in on the rows
    queued before it); a row with neither counts under ''. The empty string is literal SQL so the GROUP BY repeats the
    select's expression exactly; a bound value would be a second parameter PostgreSQL does not match."""
    return sa.func.coalesce(t.c.concurrency_key, t.c.team_id, sa.literal_column("''"))
