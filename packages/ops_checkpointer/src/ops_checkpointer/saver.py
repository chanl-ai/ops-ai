"""A LangGraph checkpointer on asyncpg.

Each checkpoint is stored whole, channel values included, as one serde blob. LangGraph hands `put` the full channel
values on every step (`create_checkpoint` reads every versioned channel), so per-channel blob tables would only
deduplicate storage; they are left out to keep the schema at two tables.

Every statement runs in a transaction that first sets `app.tenant_id`, which the row-level security policies on both
tables read. A superuser bypasses those policies, so a saver given `role` also switches to that role per transaction;
the Runtime does this locally because the compose database user is a superuser.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Coroutine,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol, cast
from urllib.parse import parse_qsl, urlencode

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
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

# The role the Runtime's statements run as, so row-level security applies. Created by migration 0004_checkpointer.
RLS_ROLE = "ops_runtime_tenant"
# Each thread's fence is the highest lease generation a write has carried; a write below it is refused (E2b).
_RAISE_FENCE = """
    INSERT INTO ops_checkpoint_fences (tenant_id, team_id, thread_id, generation) VALUES ($1, $2, $3, $4)
    ON CONFLICT (tenant_id, team_id, thread_id)
    DO UPDATE SET generation = GREATEST(ops_checkpoint_fences.generation, EXCLUDED.generation)
    RETURNING generation
"""
_READ_FENCE = "SELECT generation FROM ops_checkpoint_fences WHERE tenant_id = $1 AND team_id = $2 AND thread_id = $3"


class LeaseSupersededError(RuntimeError):
    """A checkpoint write whose lease generation is below the thread's fence, or a write with no generation on a
    fenced thread: its owner's lease was taken over."""


_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

_SELECT = """
SELECT c.thread_id, c.checkpoint_ns, c.checkpoint_id, c.parent_checkpoint_id, c.type, c.checkpoint,
       c.metadata_type, c.metadata_blob,
       (SELECT array_agg(array[convert_to(w.task_id, 'UTF8'), convert_to(w.channel, 'UTF8'),
                               convert_to(w.type, 'UTF8'), w.blob] ORDER BY w.task_path, w.task_id, w.idx)
          FROM ops_checkpoint_writes w
         WHERE w.tenant_id = c.tenant_id AND w.team_id = c.team_id AND w.thread_id = c.thread_id
           AND w.checkpoint_ns = c.checkpoint_ns AND w.checkpoint_id = c.checkpoint_id) AS writes
  FROM ops_checkpoints c
"""


type Record = Mapping[str, Any]


class Conn(Protocol):
    """The part of an asyncpg connection the saver uses. asyncpg ships no type information, so this declares it."""

    async def execute(self, query: str, *args: Any) -> str: ...
    async def executemany(self, query: str, args: Iterable[Sequence[Any]]) -> None: ...
    async def fetch(self, query: str, *args: Any) -> list[Record]: ...
    async def fetchrow(self, query: str, *args: Any) -> Record | None: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    def transaction(self) -> AbstractAsyncContextManager[Any]: ...


class Pool(Protocol):
    def acquire(self) -> AbstractAsyncContextManager[Conn]: ...
    async def close(self) -> None: ...


async def create_pool(dsn: str, *, max_size: int = 8) -> Pool:
    pool: Any = await asyncpg.create_pool(dsn, min_size=1, max_size=max_size)  # pyright: ignore[reportUnknownMemberType]
    return cast(Pool, pool)


def _configurable(config: RunnableConfig) -> dict[str, Any]:
    return config.get("configurable") or {}


class ThreadJournal(Protocol):
    """What prune asks before deleting history: the thread is closed and its run is recorded in the journal."""

    async def closed_with_journal(self, thread_id: str) -> bool: ...


def asyncpg_dsn(url: str) -> str:
    """asyncpg's DSN from the SQLAlchemy URL the services read. SQLAlchemy's asyncpg dialect takes TLS as `ssl=<mode>`,
    while asyncpg's own DSN parser takes `sslmode=<mode>` and sends any other key to the server as a setting, which
    refuses `ssl`; the key is renamed so one DSN serves both."""
    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    head, sep, query = dsn.partition("?")
    if not sep:
        return dsn
    pairs = [("sslmode" if k == "ssl" else k, v) for k, v in parse_qsl(query, keep_blank_values=True)]
    return f"{head}?{urlencode(pairs)}"


class AsyncpgSaver(BaseCheckpointSaver[str]):
    def __init__(
        self,
        pool: Pool,
        *,
        tenant_id: str | Callable[[], str],
        team_id: str,
        role: str | None = None,
        serde: SerializerProtocol | None = None,
    ) -> None:
        super().__init__(serde=serde)
        if role is not None and not _IDENT.match(role):
            raise ValueError(f"role must be a plain identifier: {role!r}")
        self.pool = pool
        self._tenant = tenant_id
        self.team_id = team_id
        self.role = role
        self.loop = asyncio.get_running_loop()

    @property
    def tenant_id(self) -> str:
        """Fixed, or read each time from the caller's scope (a context variable the service sets from the verified
        identity), so one compiled graph serves every tenant and row-level security isolates their rows."""
        return self._tenant() if callable(self._tenant) else self._tenant

    def for_scope(self, tenant_id: str, team_id: str) -> AsyncpgSaver:
        """The same pool, scoped to another tenant and team."""
        return AsyncpgSaver(self.pool, tenant_id=tenant_id, team_id=team_id, role=self.role, serde=self.serde)

    def _scope(self, _config: RunnableConfig | None) -> tuple[str, str]:
        # The scope is fixed when the saver is built and never read from a run's config: whoever builds a config
        # must not be able to choose the tenant whose rows it reads.
        return self.tenant_id, self.team_id

    @asynccontextmanager
    async def _tx(self, tenant_id: str, fence: tuple[str, int | None] | None = None) -> AsyncGenerator[Conn]:
        async with self.pool.acquire() as conn, conn.transaction():
            if self.role is not None:
                await conn.execute(f"SET LOCAL ROLE {self.role}")
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            if fence is not None:
                await self._check_fence(conn, tenant_id, *fence)
            yield conn

    async def _check_fence(self, conn: Conn, tenant_id: str, thread_id: str, generation: int | None) -> None:
        """The generation comes with the write, in the run config's `lease_generation`; the saver never reads the
        Runtime's lease table. Raising the fence locks its row until the transaction ends, so concurrent writers on
        one thread are ordered by it."""
        if generation is None:
            if await conn.fetchval(_READ_FENCE, tenant_id, self.team_id, thread_id) is not None:
                raise LeaseSupersededError(f"thread {thread_id} is fenced; this write carries no lease generation")
            return  # Never fenced: tests and tools that run a graph without a lease.
        seen = int(await conn.fetchval(_RAISE_FENCE, tenant_id, self.team_id, thread_id, generation))
        if seen > generation:
            raise LeaseSupersededError(f"lease superseded: write generation {generation} < fence {seen}")

    async def araise_fence(self, thread_id: str, generation: int) -> None:
        """Called by a new lease owner before it reads the thread, so a stalled previous owner's writes are refused
        from then on rather than from the new owner's first write. Raises LeaseSupersededError if a newer owner
        exists."""
        tenant, _ = self._scope(None)
        async with self._tx(tenant, (thread_id, generation)):
            pass

    def _tuple(self, row: Record) -> CheckpointTuple:
        thread_id, ns = row["thread_id"], row["checkpoint_ns"]

        def conf(checkpoint_id: str) -> RunnableConfig:
            return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint_id}}

        writes: list[list[bytes]] = row["writes"] or []
        return CheckpointTuple(
            config=conf(row["checkpoint_id"]),
            checkpoint=self.serde.loads_typed((row["type"], row["checkpoint"])),
            metadata=self.serde.loads_typed((row["metadata_type"], row["metadata_blob"])),
            parent_config=conf(row["parent_checkpoint_id"]) if row["parent_checkpoint_id"] else None,
            pending_writes=[
                (task.decode(), channel.decode(), self.serde.loads_typed((type_.decode(), blob)))
                for task, channel, type_, blob in writes
            ],
        )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        tenant, team = self._scope(config)
        c = _configurable(config)
        args: list[Any] = [tenant, team, c["thread_id"], c.get("checkpoint_ns", "")]
        where = "c.tenant_id = $1 AND c.team_id = $2 AND c.thread_id = $3 AND c.checkpoint_ns = $4"
        if checkpoint_id := get_checkpoint_id(config):
            args.append(checkpoint_id)
            query = f"{_SELECT} WHERE {where} AND c.checkpoint_id = $5"
        else:
            query = f"{_SELECT} WHERE {where} ORDER BY c.checkpoint_id DESC LIMIT 1"
        async with self._tx(tenant) as conn:
            row = await conn.fetchrow(query, *args)
        return self._tuple(row) if row else None

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        tenant, team = self._scope(config)
        args: list[Any] = [tenant, team]
        where = ["c.tenant_id = $1", "c.team_id = $2"]

        def add(clause: str, value: Any) -> None:
            args.append(value)
            where.append(clause.replace("?", f"${len(args)}"))

        if config is not None:
            c = _configurable(config)
            add("c.thread_id = ?", c["thread_id"])
            if (ns := c.get("checkpoint_ns")) is not None:
                add("c.checkpoint_ns = ?", ns)
            if checkpoint_id := get_checkpoint_id(config):
                add("c.checkpoint_id = ?", checkpoint_id)
        if before is not None and (before_id := get_checkpoint_id(before)):
            add("c.checkpoint_id < ?", before_id)
        if filter:
            # Containment narrows the scan; the exact equality LangGraph specifies is checked on each row below.
            add("c.metadata @> ?::jsonb", json.dumps(filter, default=str))
        query = f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY c.checkpoint_id DESC"
        if limit is not None and not filter:
            query += f" LIMIT {int(limit)}"
        async with self._tx(tenant) as conn:
            rows = await conn.fetch(query, *args)
        returned = 0
        for row in rows:
            if limit is not None and returned >= limit:
                break
            t = self._tuple(row)
            if filter and not all(t.metadata.get(k) == v for k, v in filter.items()):
                continue
            returned += 1
            yield t

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        tenant, team = self._scope(config)
        c = _configurable(config)
        thread_id, ns = c["thread_id"], c.get("checkpoint_ns", "")
        cp_type, cp_blob = self.serde.dumps_typed(checkpoint)
        md_type, md_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        md_json = json.dumps(get_serializable_checkpoint_metadata(config, metadata), default=str)
        async with self._tx(tenant, (thread_id, c.get("lease_generation"))) as conn:
            await conn.execute(
                """
                INSERT INTO ops_checkpoints (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id,
                    parent_checkpoint_id, type, checkpoint, metadata_type, metadata_blob, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                ON CONFLICT (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET
                    type = EXCLUDED.type, checkpoint = EXCLUDED.checkpoint, metadata_type = EXCLUDED.metadata_type,
                    metadata_blob = EXCLUDED.metadata_blob, metadata = EXCLUDED.metadata
                """,
                tenant,
                team,
                thread_id,
                ns,
                checkpoint["id"],
                c.get("checkpoint_id"),
                cp_type,
                cp_blob,
                md_type,
                md_blob,
                md_json,
            )
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint["id"]}}

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        tenant, team = self._scope(config)
        c = _configurable(config)
        key = (tenant, team, c["thread_id"], c.get("checkpoint_ns", ""), c["checkpoint_id"], task_id)
        insert = """
            INSERT INTO ops_checkpoint_writes (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id, task_id,
                idx, channel, type, blob, task_path)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        """
        regular: list[tuple[Any, ...]] = []
        special: list[tuple[Any, ...]] = []
        for i, (channel, value) in enumerate(writes):
            idx = WRITES_IDX_MAP.get(channel, i)
            row = (*key, idx, channel, *self.serde.dumps_typed(value), task_path)
            # A replayed task writes the same regular rows again and the first copy stands; errors, interrupts and
            # resumes are replaced so the latest one is what a resume sees.
            (special if idx < 0 else regular).append(row)
        async with self._tx(tenant, (c["thread_id"], c.get("lease_generation"))) as conn:
            if regular:
                await conn.executemany(insert + " DO NOTHING", regular)
            if special:
                await conn.executemany(
                    insert + " DO UPDATE SET channel = EXCLUDED.channel, type = EXCLUDED.type, blob = EXCLUDED.blob,"
                    " task_path = EXCLUDED.task_path",
                    special,
                )

    async def adelete_thread(self, thread_id: str) -> None:
        async with self._tx(self.tenant_id) as conn:
            for table in ("ops_checkpoint_writes", "ops_checkpoints"):
                await conn.execute(
                    f"DELETE FROM {table} WHERE tenant_id = $1 AND team_id = $2 AND thread_id = $3",
                    self.tenant_id,
                    self.team_id,
                    thread_id,
                )

    async def adelete_for_runs(self, run_ids: Sequence[str]) -> None:
        async with self._tx(self.tenant_id) as conn:
            await conn.execute(
                """
                WITH d AS (
                    DELETE FROM ops_checkpoints
                     WHERE tenant_id = $1 AND team_id = $2 AND metadata->>'run_id' = ANY($3::text[])
                    RETURNING thread_id, checkpoint_ns, checkpoint_id)
                DELETE FROM ops_checkpoint_writes w USING d
                 WHERE w.tenant_id = $1 AND w.team_id = $2 AND w.thread_id = d.thread_id
                   AND w.checkpoint_ns = d.checkpoint_ns AND w.checkpoint_id = d.checkpoint_id
                """,
                self.tenant_id,
                self.team_id,
                list(run_ids),
            )

    async def acopy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        args = (self.tenant_id, self.team_id, source_thread_id, target_thread_id)
        async with self._tx(self.tenant_id) as conn:
            await conn.execute(
                """
                INSERT INTO ops_checkpoints (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id,
                    parent_checkpoint_id, type, checkpoint, metadata_type, metadata_blob, metadata)
                SELECT tenant_id, team_id, $4, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint,
                       metadata_type, metadata_blob, metadata
                  FROM ops_checkpoints WHERE tenant_id = $1 AND team_id = $2 AND thread_id = $3
                ON CONFLICT DO NOTHING
                """,
                *args,
            )
            await conn.execute(
                """
                INSERT INTO ops_checkpoint_writes (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id,
                    task_id, idx, channel, type, blob, task_path)
                SELECT tenant_id, team_id, $4, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob,
                       task_path
                  FROM ops_checkpoint_writes WHERE tenant_id = $1 AND team_id = $2 AND thread_id = $3
                ON CONFLICT DO NOTHING
                """,
                *args,
            )

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
        async with self._tx(self.tenant_id) as conn:
            await conn.execute(
                """
                WITH latest AS (
                    SELECT thread_id, checkpoint_ns, max(checkpoint_id) AS checkpoint_id FROM ops_checkpoints
                     WHERE tenant_id = $1 AND team_id = $2 AND thread_id = ANY($3::text[])
                     GROUP BY thread_id, checkpoint_ns),
                d AS (
                    DELETE FROM ops_checkpoints c USING latest l
                     WHERE c.tenant_id = $1 AND c.team_id = $2 AND c.thread_id = l.thread_id
                       AND c.checkpoint_ns = l.checkpoint_ns AND c.checkpoint_id < l.checkpoint_id
                    RETURNING c.thread_id, c.checkpoint_ns, c.checkpoint_id)
                DELETE FROM ops_checkpoint_writes w USING d
                 WHERE w.tenant_id = $1 AND w.team_id = $2 AND w.thread_id = d.thread_id
                   AND w.checkpoint_ns = d.checkpoint_ns AND w.checkpoint_id = d.checkpoint_id
                """,
                self.tenant_id,
                self.team_id,
                list(thread_ids),
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
                raise asyncio.InvalidStateError("Use the async methods of AsyncpgSaver from inside its event loop")
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
    tenant_id: str | Callable[[], str],
    team_id: str,
    role: str | None = RLS_ROLE,
    max_size: int = 8,
) -> AsyncGenerator[AsyncpgSaver]:
    """A saver on its own pool. The tables come from the Alembic migrations, so run `make migrate` first."""
    pool = await create_pool(asyncpg_dsn(database_url), max_size=max_size)
    try:
        yield AsyncpgSaver(pool, tenant_id=tenant_id, team_id=team_id, role=role)
    finally:
        await pool.close()
