"""A LangGraph checkpointer on SQLAlchemy Core, the same statements on PostgreSQL and SQL Server.

Each checkpoint is stored whole, channel values included, as one serde blob. LangGraph hands `put` the full channel
values on every step (`create_checkpoint` reads every versioned channel), so per-channel blob tables would only
deduplicate storage; they are left out to keep the schema at two tables.

Every statement runs in `ops_store.isolation.isolated_tx`, which writes the tenant and team where the tables' policies
read them (`set_config` on PostgreSQL, SESSION_CONTEXT on SQL Server). The Runtime's saver takes both from the caller's
isolation context, so one compiled graph serves every tenant and team: a run acts as its thread's team, a write with
no team in the context is refused (every row is in exactly one team), and a tenant-wide read finds a thread whichever
team holds it. A PostgreSQL superuser
bypasses row-level security, so a saver given `role` also switches to that role per transaction; the Runtime does this
locally because the compose database user is a superuser. Where PostgreSQL and SQL Server differ (upserts, row locks)
the statement comes from `ops_store.dialect`.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Coroutine,
    Iterator,
    Sequence,
)
from contextlib import asynccontextmanager, nullcontext
from typing import Any, Protocol

import sqlalchemy as sa
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
    get_serializable_checkpoint_metadata,
)
from langgraph.checkpoint.serde.base import SerializerProtocol
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import isolation
from ops_store.database import open_database
from ops_store.dialect import insert_ignore, locked, upsert

from .tables import ops_checkpoint_fences as fences
from .tables import ops_checkpoint_writes as writes_t
from .tables import ops_checkpoints as cps

# The role the Runtime's statements run as on PostgreSQL, so row-level security applies. Created by migration 0004.
RLS_ROLE = "ops_runtime_tenant"
_CP_KEY = ("tenant_id", "team_id", "thread_id", "checkpoint_ns", "checkpoint_id")
_WRITE_KEY = (*_CP_KEY, "task_id", "idx")
_FENCE_KEY = ("tenant_id", "team_id", "thread_id")
# SQL Server takes at most 2100 parameters in a statement; a history's pending writes are read in chunks well below.
_CHUNK = 500
# Each checkpoint's pending writes (task, channel, value), by (thread, namespace, checkpoint).
type Pending = dict[tuple[str, str, str], list[tuple[str, str, Any]]]


class NoTeamError(RuntimeError):
    """A checkpoint write with no team in the isolation context: every checkpoint belongs to exactly one team, so a
    tenant-wide or system context may read checkpoints but not write one."""


class LeaseSupersededError(RuntimeError):
    """A checkpoint write whose lease generation is below the thread's fence, or a write with no generation on a
    fenced thread: its owner's lease was taken over."""


def _configurable(config: RunnableConfig) -> dict[str, Any]:
    return config.get("configurable") or {}


class ThreadJournal(Protocol):
    """What prune asks before deleting history: the thread is closed and its run is recorded in the journal."""

    async def closed_with_journal(self, thread_id: str) -> bool: ...


class CheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(
        self,
        db: AsyncEngine,
        *,
        tenant_id: str | None = None,
        team_id: str | None = None,
        role: str | None = None,
        serde: SerializerProtocol | None = None,
    ) -> None:
        """With no tenant, the tenant and team are read from the isolation context for each call; a tenant and team
        given here fix them (tests, tools)."""
        super().__init__(serde=serde)
        if (tenant_id is None) != (team_id is None):
            raise ValueError("give both a tenant and a team, or neither to read them from the isolation context")
        self.db = db
        self._tenant = tenant_id
        self._team = team_id
        self.role = role
        self.loop = asyncio.get_running_loop()

    @property
    def tenant_id(self) -> str:
        return self._tenant if self._tenant is not None else isolation.tenant()

    def for_scope(self, tenant_id: str, team_id: str) -> CheckpointSaver:
        """The same engine, fixed to a tenant and team."""
        return CheckpointSaver(self.db, tenant_id=tenant_id, team_id=team_id, role=self.role, serde=self.serde)

    def _who(self, *, writing: bool) -> tuple[str, str | None]:
        """The tenant and team a call acts for. Never read from a run's config: whoever builds a config must not be
        able to choose the rows it reads or writes."""
        if self._tenant is not None:
            tenant, team = self._tenant, self._team
        else:
            tenant, team = isolation.tenant(), isolation.team()
        if writing and not team:
            raise NoTeamError("a checkpoint write needs a team: run the graph as its thread's team")
        return tenant, team

    def _writer(self) -> tuple[str, str]:
        tenant, team = self._who(writing=True)
        assert team is not None
        return tenant, team

    @asynccontextmanager
    async def _tx(
        self, tenant_id: str, team_id: str | None, fence: tuple[str, int | None] | None = None
    ) -> AsyncGenerator[AsyncConnection]:
        # A saver fixed to a scope acts as it; otherwise the caller's context is already the scope.
        with isolation.scope(tenant_id, team_id) if self._tenant is not None else nullcontext():
            async with isolation.isolated_tx(self.db, role=self.role) as conn:
                if fence is not None:
                    assert team_id is not None
                    await self._check_fence(conn, tenant_id, team_id, *fence)
                yield conn

    def _mine(self, table: sa.Table, tenant_id: str, team_id: str | None) -> list[sa.ColumnElement[bool]]:
        """The rows of the tenant, and of the team when one is named; a tenant-wide read names none."""
        mine = [table.c.tenant_id == tenant_id]
        return [*mine, table.c.team_id == team_id] if team_id else mine

    async def _check_fence(
        self, conn: AsyncConnection, tenant_id: str, team_id: str, thread_id: str, generation: int | None
    ) -> None:
        """The generation comes with the write, in the run config's `lease_generation`; the saver never reads the
        Runtime's lease table. The fence row stays locked until the transaction ends, so concurrent writers on one
        thread are ordered by it."""
        key = {"tenant_id": tenant_id, "team_id": team_id, "thread_id": thread_id}
        held = sa.select(fences.c.generation).where(*(fences.c[k] == v for k, v in key.items()))
        if generation is None:
            if (await conn.execute(held)).scalar_one_or_none() is not None:
                raise LeaseSupersededError(f"thread {thread_id} is fenced; this write carries no lease generation")
            return  # Never fenced: tests and tools that run a graph without a lease.
        seen = (await conn.execute(locked(held, fences))).scalar_one_or_none()
        if seen is None:
            # Two first writers may both find no row: one inserts, the other's insert does nothing, and both read the
            # row the winner wrote, locked.
            await conn.execute(insert_ignore(conn, fences, {**key, "generation": generation}, keys=_FENCE_KEY))
            seen = (await conn.execute(locked(held, fences))).scalar_one()
        if seen < generation:
            await conn.execute(
                fences.update().where(*(fences.c[k] == v for k, v in key.items())).values(generation=generation)
            )
        elif seen > generation:
            raise LeaseSupersededError(f"lease superseded: write generation {generation} < fence {seen}")

    async def araise_fence(self, thread_id: str, generation: int) -> None:
        """Called by a new lease owner before it reads the thread, so a stalled previous owner's writes are refused
        from then on rather than from the new owner's first write. Raises LeaseSupersededError if a newer owner
        exists."""
        tenant, team = self._writer()
        async with self._tx(tenant, team, (thread_id, generation)):
            pass

    async def _pending(
        self, conn: AsyncConnection, tenant_id: str, team_id: str | None, rows: Sequence[sa.Row[Any]]
    ) -> Pending:
        """Each checkpoint's pending writes, in LangGraph's order, read in chunks of checkpoints."""
        found: Pending = {}
        for i in range(0, len(rows), _CHUNK):
            chunk = rows[i : i + _CHUNK]
            query = (
                sa.select(writes_t)
                .where(
                    *self._mine(writes_t, tenant_id, team_id),
                    writes_t.c.thread_id.in_({r.thread_id for r in chunk}),
                    writes_t.c.checkpoint_id.in_({r.checkpoint_id for r in chunk}),
                )
                .order_by(writes_t.c.task_path, writes_t.c.task_id, writes_t.c.idx)
            )
            for w in await conn.execute(query):
                value = self.serde.loads_typed((w.type, w.blob))
                found.setdefault((w.thread_id, w.checkpoint_ns, w.checkpoint_id), []).append(
                    (w.task_id, w.channel, value)
                )
        return found

    def _tuple(self, row: sa.Row[Any], pending: Pending) -> CheckpointTuple:
        thread_id, ns = row.thread_id, row.checkpoint_ns

        def conf(checkpoint_id: str) -> RunnableConfig:
            return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint_id}}

        return CheckpointTuple(
            config=conf(row.checkpoint_id),
            checkpoint=self.serde.loads_typed((row.type, row.checkpoint)),
            metadata=self.serde.loads_typed((row.metadata_type, row.metadata_blob)),
            parent_config=conf(row.parent_checkpoint_id) if row.parent_checkpoint_id else None,
            pending_writes=pending.get((thread_id, ns, row.checkpoint_id), []),
        )

    def _matches(self, row: sa.Row[Any], filter: dict[str, Any]) -> bool:
        metadata = self.serde.loads_typed((row.metadata_type, row.metadata_blob))
        return all(metadata.get(k) == v for k, v in filter.items())

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        tenant, team = self._who(writing=False)
        c = _configurable(config)
        query = sa.select(cps).where(
            *self._mine(cps, tenant, team),
            cps.c.thread_id == c["thread_id"],
            cps.c.checkpoint_ns == c.get("checkpoint_ns", ""),
        )
        if checkpoint_id := get_checkpoint_id(config):
            query = query.where(cps.c.checkpoint_id == checkpoint_id)
        else:
            query = query.order_by(cps.c.checkpoint_id.desc()).limit(1)
        async with self._tx(tenant, team) as conn:
            row = (await conn.execute(query)).first()
            if row is None:
                return None
            return self._tuple(row, await self._pending(conn, tenant, team, [row]))

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        tenant, team = self._who(writing=False)
        query = sa.select(cps).where(*self._mine(cps, tenant, team))
        if config is not None:
            c = _configurable(config)
            query = query.where(cps.c.thread_id == c["thread_id"])
            if (ns := c.get("checkpoint_ns")) is not None:
                query = query.where(cps.c.checkpoint_ns == ns)
            if checkpoint_id := get_checkpoint_id(config):
                query = query.where(cps.c.checkpoint_id == checkpoint_id)
        if before is not None and (before_id := get_checkpoint_id(before)):
            query = query.where(cps.c.checkpoint_id < before_id)
        if filter and "run_id" in filter:
            # The one key with its own column narrows the scan; every key, this one included, is compared below with
            # the exact equality LangGraph specifies.
            query = query.where(cps.c.run_id == str(filter["run_id"]))
        query = query.order_by(cps.c.checkpoint_id.desc())
        if limit is not None and not filter:
            query = query.limit(int(limit))
        async with self._tx(tenant, team) as conn:
            rows = list(await conn.execute(query))
            if filter:
                rows = [r for r in rows if self._matches(r, filter)]
            if limit is not None:
                rows = rows[:limit]
            pending = await self._pending(conn, tenant, team, rows)
        for row in rows:
            yield self._tuple(row, pending)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        tenant, team = self._writer()
        c = _configurable(config)
        thread_id, ns = c["thread_id"], c.get("checkpoint_ns", "")
        cp_type, cp_blob = self.serde.dumps_typed(checkpoint)
        md_type, md_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        # The JSON column holds what a filter compares, as LangGraph's own savers store it; a value JSON cannot hold
        # is kept as its text.
        md = json.loads(json.dumps(get_serializable_checkpoint_metadata(config, metadata), default=str))
        row = {
            "tenant_id": tenant,
            "team_id": team,
            "thread_id": thread_id,
            "checkpoint_ns": ns,
            "checkpoint_id": checkpoint["id"],
            "parent_checkpoint_id": c.get("checkpoint_id"),
            "type": cp_type,
            "checkpoint": cp_blob,
            "metadata_type": md_type,
            "metadata_blob": md_blob,
            "metadata": md,
            "run_id": None if (run_id := md.get("run_id")) is None else str(run_id),
        }
        async with self._tx(tenant, team, (thread_id, c.get("lease_generation"))) as conn:
            update = ["type", "checkpoint", "metadata_type", "metadata_blob", "metadata", "run_id"]
            await conn.execute(upsert(conn, cps, row, keys=_CP_KEY, update=update))
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint["id"]}}

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        tenant, team = self._writer()
        c = _configurable(config)
        key = {
            "tenant_id": tenant,
            "team_id": team,
            "thread_id": c["thread_id"],
            "checkpoint_ns": c.get("checkpoint_ns", ""),
            "checkpoint_id": c["checkpoint_id"],
            "task_id": task_id,
        }
        async with self._tx(tenant, team, (c["thread_id"], c.get("lease_generation"))) as conn:
            for i, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, i)
                type_, blob = self.serde.dumps_typed(value)
                row = {**key, "idx": idx, "channel": channel, "type": type_, "blob": blob, "task_path": task_path}
                # A replayed task writes the same regular rows again and the first copy stands; errors, interrupts and
                # resumes are replaced so the latest one is what a resume sees.
                if idx < 0:
                    await conn.execute(upsert(conn, writes_t, row, keys=_WRITE_KEY))
                else:
                    await conn.execute(insert_ignore(conn, writes_t, row, keys=_WRITE_KEY))

    async def adelete_thread(self, thread_id: str) -> None:
        tenant, team = self._who(writing=False)
        async with self._tx(tenant, team) as conn:
            for table in (writes_t, cps):
                await conn.execute(
                    table.delete().where(*self._mine(table, tenant, team), table.c.thread_id == thread_id)
                )

    def _of_checkpoint(self, tenant_id: str, team_id: str | None, *where: sa.ColumnElement[bool]) -> sa.Exists:
        """A pending write's checkpoint exists and matches `where`."""
        return sa.exists().where(
            *self._mine(cps, tenant_id, team_id),
            cps.c.team_id == writes_t.c.team_id,
            cps.c.thread_id == writes_t.c.thread_id,
            cps.c.checkpoint_ns == writes_t.c.checkpoint_ns,
            cps.c.checkpoint_id == writes_t.c.checkpoint_id,
            *where,
        )

    async def adelete_for_runs(self, run_ids: Sequence[str]) -> None:
        (tenant, team), runs = self._who(writing=False), list(run_ids)
        async with self._tx(tenant, team) as conn:
            await conn.execute(
                writes_t.delete().where(
                    *self._mine(writes_t, tenant, team), self._of_checkpoint(tenant, team, cps.c.run_id.in_(runs))
                )
            )
            await conn.execute(cps.delete().where(*self._mine(cps, tenant, team), cps.c.run_id.in_(runs)))

    async def acopy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        tenant, team = self._writer()
        async with self._tx(tenant, team) as conn:
            for table, key in ((cps, _CP_KEY), (writes_t, _WRITE_KEY)):
                target = table.alias("target")
                cols = [c.name for c in table.columns]
                copied = sa.select(
                    *(
                        sa.literal(target_thread_id, table.c.thread_id.type).label(n)
                        if n == "thread_id"
                        else table.c[n]
                        for n in cols
                    )
                ).where(
                    *self._mine(table, tenant, team),
                    table.c.thread_id == source_thread_id,
                    # A row the target already holds stays as it is.
                    ~sa.exists().where(
                        target.c.thread_id == target_thread_id,
                        *(target.c[k] == table.c[k] for k in key if k != "thread_id"),
                    ),
                )
                await conn.execute(table.insert().from_select(cols, copied))

    async def aprune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        """`keep_latest` keeps the newest checkpoint in each namespace; `delete` removes the threads' history.

        The Runtime's graphs use no DeltaChannel, so the kept checkpoint never depends on a deleted ancestor.
        """
        if strategy == "delete":
            for thread_id in thread_ids:
                await self.adelete_thread(thread_id)
            return
        if strategy != "keep_latest":
            raise ValueError(f"unknown prune strategy: {strategy}")
        (tenant, team), threads = self._who(writing=False), list(thread_ids)
        newest = cps.alias("newest")

        def latest(table: sa.Table) -> sa.ScalarSelect[Any]:
            return (
                sa.select(sa.func.max(newest.c.checkpoint_id))
                .where(
                    newest.c.tenant_id == tenant,
                    newest.c.team_id == table.c.team_id,
                    newest.c.thread_id == table.c.thread_id,
                    newest.c.checkpoint_ns == table.c.checkpoint_ns,
                )
                .scalar_subquery()
            )

        async with self._tx(tenant, team) as conn:
            for table in (writes_t, cps):
                await conn.execute(
                    table.delete().where(
                        *self._mine(table, tenant, team),
                        table.c.thread_id.in_(threads),
                        table.c.checkpoint_id < latest(table),
                    )
                )

    async def prune_thread(self, thread_id: str, journal: ThreadJournal, *, strategy: str = "keep_latest") -> bool:
        """Drops a closed thread's step history once the journal holds its record. Returns whether it pruned.

        Checkpoints are the resume state; the journal is the long-term record. Pruning before the journal row exists
        would leave a finished run with neither.
        """
        if not await journal.closed_with_journal(thread_id):
            return False
        await self.aprune([thread_id], strategy=strategy)
        return True

    def get_next_version(self, current: str | None, channel: None) -> str:
        # Same format as LangGraph's own savers: a zero-padded counter that sorts as text, plus a random tiebreak.
        current_v = 0 if current is None else int(str(current).split(".")[0])
        return f"{current_v + 1:032}.{random.random():016}"

    # LangGraph calls the sync methods from sync graph APIs (`graph.invoke`, `get_state`). They run the async method
    # on the loop that owns the pool, which only works from another thread.
    def _sync[T](self, coro: Coroutine[Any, Any, T]) -> T:
        try:
            if asyncio.get_running_loop() is self.loop:
                coro.close()
                raise asyncio.InvalidStateError("Use the async methods of CheckpointSaver from inside its event loop")
        except RuntimeError:
            pass
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self._sync(self.aget_tuple(config))

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        async def collect() -> list[CheckpointTuple]:
            return [t async for t in self.alist(config, filter=filter, before=before, limit=limit)]

        return iter(self._sync(collect()))

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self._sync(self.aput(config, checkpoint, metadata, new_versions))

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self._sync(self.aput_writes(config, writes, task_id, task_path))

    def delete_thread(self, thread_id: str) -> None:
        self._sync(self.adelete_thread(thread_id))

    def delete_for_runs(self, run_ids: Sequence[str]) -> None:
        self._sync(self.adelete_for_runs(run_ids))

    def copy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        self._sync(self.acopy_thread(source_thread_id, target_thread_id))

    def prune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        self._sync(self.aprune(thread_ids, strategy=strategy))


@asynccontextmanager
async def open_saver(
    database_url: str,
    *,
    tenant_id: str | None = None,
    team_id: str | None = None,
    role: str | None = RLS_ROLE,
    max_size: int = 8,
) -> AsyncGenerator[CheckpointSaver]:
    """A saver on its own engine. The tables come from the Alembic migrations or the SQL Server bundle, so run
    `make migrate` (or install the bundle) first."""
    db = open_database(database_url, pool_size=max_size)
    try:
        yield CheckpointSaver(db, tenant_id=tenant_id, team_id=team_id, role=role)
    finally:
        await db.dispose()
