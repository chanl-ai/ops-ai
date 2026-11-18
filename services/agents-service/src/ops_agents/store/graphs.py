"""Graph threads, versions and runs (SQLAlchemy Core, no ORM). Console chat is a facade over these threads and the
event log (chat_threads.py); its own tables were dropped in migration 0017.

Column types are the portable ones (JSON, not JSONB) so the API tests run on SQLite and production on PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any, ClassVar

import sqlalchemy as sa
import sqlalchemy.exc
from pydantic import BaseModel, JsonValue

from ops_service_kit import narrow
from ops_service_kit.http import Json, Out
from ops_store import Guarantee
from ops_store.dialect import insert_ignore, locked
from ops_store.listing import LISTED
from ops_store.rows import one, rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import any_team, team_visible

from .base import metadata
from .leases import check_fence
from .tenancy import CLAIM_THREAD, RuntimeStore, current_tenant

graph_threads = sa.Table(
    "graph_threads",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("graph", sa.String(64), nullable=False, index=True, info=LISTED),
    sa.Column("meta", sa.JSON, nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False, info=LISTED),
    sa.Column("status", sa.String(16), nullable=False),
    # Set for definition-built workflows: the version the thread started on and its digest. Every run and resume
    # compiles this version, so later publishes do not change a running or paused case.
    sa.Column("version", sa.Integer),
    sa.Column("digest", sa.String(64)),
    # A channel's key for the thing that started the case (mailbox: deployment id + Message-ID). Unique, so a
    # redelivered message finds its case instead of opening a second one (E6).
    sa.Column("external_key", sa.String(512)),
    sa.Column("deployment_id", sa.String(64), index=True),
    # A follow-up case opened by a reply to a closed one points back at it.
    sa.Column("parent_thread_id", sa.String(64), index=True),
    # A chat thread's overrides within its agent's limits, applied to every turn (activities/overrides.py).
    sa.Column("overrides", sa.JSON),
    # The email of the person the thread belongs to, the same as its meta's `ownerEmail` and written with it
    # (`_owner`), so a list or count by owner reads a column, not each row's JSON (migration 0105).
    sa.Column("owner", sa.String(320)),
    # Set from the request's or loop's tenant (store/tenancy.py), never from a body; PostgreSQL RLS reads it (0021).
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, index=True),
    # Per tenant, so one tenant's key neither collides with nor reveals another's.
    sa.UniqueConstraint("tenant_id", "external_key", name="uq_graph_threads_tenant_external_key"),
    # A team's thread list, newest first.
    sa.Index("ix_graph_threads_team_updated", "tenant_id", "team_id", "updated_at"),
    # A person's own threads.
    sa.Index("ix_graph_threads_owner", "tenant_id", "owner"),
    # Held to the caller's team by the database too (migration 0073): another team's thread is not found.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

graph_versions = sa.Table(
    "graph_versions",
    metadata,
    # The workflow's tenant (agents 0106), with no default (agents 0109).
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    sa.Column("name", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("definition", sa.JSON, nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    # A digest is stored once per tenant.
    sa.UniqueConstraint("tenant_id", "digest", name="uq_graph_versions_tenant_digest"),
    info=TENANT_SCOPED,
)

graph_runs = sa.Table(
    "graph_runs",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("thread_id", sa.String(64), sa.ForeignKey("graph_threads.id"), nullable=False, index=True),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    # The events the run streamed, so a repeated run id replays them instead of running the graph again.
    sa.Column("events", sa.JSON, nullable=False),
    # The run's input, so a recovery can restart a run that crashed before LangGraph wrote its first checkpoint.
    sa.Column("input", sa.JSON),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("finished_at", sa.String(32)),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, index=True),
    # The thread's team, copied when the run starts, so the policy holds the run without reading its thread.
    sa.Column("team_id", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class RunThread(BaseModel):
    """A thread as a workflow's runs list shows it."""

    id: str
    status: str
    version: int | None
    meta: dict[str, JsonValue]
    created_at: str
    updated_at: str


class ThreadRow(BaseModel):
    """A `graph_threads` row, every column, refused when its meta is not an object or its overrides are neither an
    object nor null: the lists, reviews and `runs.resolve` that read it fail on such a row."""

    id: str
    graph: str
    meta: dict[str, JsonValue]
    team_id: str
    created_at: str
    updated_at: str
    status: str
    version: int | None
    digest: str | None
    external_key: str | None
    deployment_id: str | None
    parent_thread_id: str | None
    overrides: dict[str, JsonValue] | None
    owner: str | None
    tenant_id: str


class StoredThread(BaseModel):
    """A `graph_threads` row, every column, as stored: `meta` and `overrides` are whatever JSON the row holds, for the
    reads that never refused a row (`thread`, `threads`, `open_thread`). `meta_object` is the object view; access and
    list rules read a strict `ThreadRow` instead."""

    id: str
    graph: str
    meta: JsonValue
    team_id: str
    created_at: str
    updated_at: str
    status: str
    version: int | None
    digest: str | None
    external_key: str | None
    deployment_id: str | None
    parent_thread_id: str | None
    overrides: JsonValue
    owner: str | None
    tenant_id: str

    def meta_object(self) -> Json:
        """The meta as an object, empty when unset (null or empty); any other value fails as `Malformed`."""
        return narrow.an_object(self.meta or {}, "thread meta")


class StoredVersion(BaseModel):
    """A stored workflow version's definition and digest."""

    name: str
    version: int
    digest: str
    definition: dict[str, JsonValue]


class VersionRow(Out):
    """A `graph_versions` row, every column: one stored version of a definition-built workflow."""

    tenant_id: str
    name: str
    version: int
    digest: str
    definition: Json
    created_at: str


class RunRow(Out):
    """A `graph_runs` row, every column. `input` is what the run was started with (a message, a resume value)."""

    id: str
    thread_id: str
    kind: str
    status: str
    events: list[Json]
    input: JsonValue
    created_at: str
    finished_at: str | None
    tenant_id: str
    team_id: str


class RunSummary(Out):
    """A run without its events: its kind, status, input and finish."""

    thread_id: str
    kind: str
    status: str
    input: JsonValue
    finished_at: str | None


class RunJournal(BaseModel):
    """One run's kind and streamed events, by its thread."""

    thread_id: str
    kind: str
    events: list[dict[str, JsonValue]]


def mine(table: sa.Table) -> sa.ColumnElement[bool]:
    """The tenant filter in the query itself, for SQLite; on PostgreSQL RLS applies it as well."""
    return table.c.tenant_id == current_tenant()


def _owner(owner_email: object) -> str | None:
    """The owner column's value for a meta's `ownerEmail`: None when it names nobody."""
    return str(owner_email) if owner_email else None


class GraphStore(RuntimeStore):
    # Run and status writes are checked against the lease generation in their own transaction (TRANSACTION); a
    # thread found or created by external key, and a version stored once per digest, rest on unique inserts (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    async def create_thread(
        self,
        thread_id: str,
        graph: str,
        meta: Json,
        team_id: str,
        now: str,
        *,
        version: int | None = None,
        digest: str | None = None,
    ) -> None:
        async with self.tx() as c:
            await c.execute(
                graph_threads.insert().values(
                    id=thread_id,
                    graph=graph,
                    meta=meta,
                    owner=_owner(meta.get("ownerEmail")),
                    team_id=team_id,
                    created_at=now,
                    updated_at=now,
                    status="idle",
                    version=version,
                    digest=digest,
                )
            )

    async def owner_of(self, thread_id: str) -> tuple[str, str] | None:
        """Which tenant and team a thread belongs to, read past row-level security. For the sweeper and the timer
        poller only, which claim work before they know its owner (tests/store/test_tenancy.py holds the callers)."""
        t = graph_threads
        async with self.system_tx(CLAIM_THREAD) as c:
            q = sa.select(t.c.tenant_id, t.c.team_id).where(t.c.id == thread_id, any_team(t, "a loop finds its owner"))
            row = (await c.execute(q)).first()
        return (str(row[0]), str(row[1])) if row else None

    async def thread_by_key(self, external_key: str) -> StoredThread | None:
        async with self.tx() as c:
            q = graph_threads.select().where(
                graph_threads.c.external_key == external_key, mine(graph_threads), team_visible(graph_threads)
            )
            return await one(c, q.limit(1), StoredThread)

    async def find_or_create_thread(
        self, thread_id: str, graph: str, meta: Json, team_id: str, now: str, *, external_key: str
    ) -> tuple[dict[str, Any], bool]:
        """`open_thread` with the row as a mapping, for the callers that still read a thread by key."""
        row, created = await self.open_thread(thread_id, graph, meta, team_id, now, external_key=external_key)
        return row.model_dump(), created

    async def open_thread(
        self,
        thread_id: str,
        graph: str,
        meta: Json,
        team_id: str,
        now: str,
        *,
        external_key: str,
        deployment_id: str | None = None,
        parent_thread_id: str | None = None,
        version: int | None = None,
        digest: str | None = None,
    ) -> tuple[StoredThread, bool]:
        """The thread for `external_key`, created when there is none, in one transaction: the insert either wins or
        conflicts on the unique key, and the conflict path reads the existing row. Returns (row, created)."""
        values = {
            "id": thread_id,
            "graph": graph,
            "meta": meta,
            "owner": _owner(meta.get("ownerEmail")),
            "team_id": team_id,
            "created_at": now,
            "updated_at": now,
            "status": "idle",
            "version": version,
            "digest": digest,
            "external_key": external_key,
            "deployment_id": deployment_id,
            "parent_thread_id": parent_thread_id,
            "tenant_id": current_tenant(),
        }
        async with self.tx() as c:
            stmt = insert_ignore(c, graph_threads, values, keys=["tenant_id", "external_key"])
            created = (await c.execute(stmt)).rowcount == 1
            row = await one(
                c,
                graph_threads.select().where(
                    graph_threads.c.external_key == external_key, mine(graph_threads), team_visible(graph_threads)
                ),
                StoredThread,
            )
            if row is None:
                # Inside the transaction, so the insert rolls back with it (another team's thread holds the key).
                raise sqlalchemy.exc.NoResultFound("No row was found when one was required")
        return row, created

    async def pin(self, thread_id: str, version: int, digest: str, now: str) -> None:
        async with self.tx() as c:
            await c.execute(
                graph_threads.update()
                .where(graph_threads.c.id == thread_id)
                .values(version=version, digest=digest, updated_at=now)
            )

    async def versions(self, name: str) -> list[VersionRow]:
        q = (
            sa.select(graph_versions)
            .where(mine(graph_versions), graph_versions.c.name == name)
            .order_by(graph_versions.c.version)
        )
        async with self.tx() as c:
            return await rows(c, q, VersionRow)

    async def version(self, name: str, version: int) -> VersionRow | None:
        q = sa.select(graph_versions).where(
            mine(graph_versions), graph_versions.c.name == name, graph_versions.c.version == version
        )
        async with self.tx() as c:
            return await one(c, q, VersionRow)

    async def threads_named(self, thread_ids: Sequence[str]) -> list[ThreadRow]:
        """The named threads the caller may see, in one statement; `thread_ids` is bounded by the caller (a batch of
        a stream's events)."""
        if not thread_ids:
            return []
        t = graph_threads
        q = sa.select(*(t.c[name] for name in ThreadRow.model_fields)).where(
            t.c.id.in_(list(thread_ids)), mine(t), team_visible(t)
        )
        async with self.tx() as c:
            return await rows(c, q, ThreadRow)

    async def versions_at(self, pairs: Collection[tuple[str, int]]) -> dict[tuple[str, int], StoredVersion]:
        """The named workflow versions in one statement, by (name, version); a pair with no stored version is left
        out. Read by the names and versions asked for, then matched in pairs, so no tuple IN is needed."""
        if not pairs:
            return {}
        v = graph_versions.c
        q = sa.select(v.name, v.version, v.digest, v.definition).where(
            mine(graph_versions),
            v.name.in_(sorted({n for n, _ in pairs})),
            v.version.in_(sorted({n for _, n in pairs})),
        )
        async with self.tx() as c:
            found = await rows(c, q, StoredVersion)
        return {(r.name, r.version): r for r in found if (r.name, r.version) in pairs}

    async def publish(self, name: str, definition: Json, digest: str, now: str) -> int:
        """Stores the next version of a workflow; a definition already stored under its digest returns that version."""
        async with self.tx() as c:
            same = (
                await c.execute(
                    sa.select(graph_versions.c.version).where(mine(graph_versions), graph_versions.c.digest == digest)
                )
            ).first()
            if same:
                return int(same.version)
            latest = (
                await c.execute(
                    sa.select(sa.func.max(graph_versions.c.version)).where(
                        mine(graph_versions), graph_versions.c.name == name
                    )
                )
            ).scalar()
            version = int(latest or 0) + 1
            await c.execute(
                graph_versions.insert().values(
                    name=name,
                    version=version,
                    digest=digest,
                    definition={**definition, "version": version},
                    created_at=now,
                )
            )
            return version

    async def thread_row(self, thread_id: str) -> StoredThread | None:
        q = graph_threads.select().where(
            graph_threads.c.id == thread_id, mine(graph_threads), team_visible(graph_threads)
        )
        async with self.tx() as c:
            return await one(c, q, StoredThread)

    async def thread(self, thread_id: str) -> dict[str, Any] | None:
        """`thread_row` as a mapping, for the callers that still read a thread by key."""
        row = await self.thread_row(thread_id)
        return row.model_dump() if row is not None else None

    async def thread_rows(self, graph: str | None) -> list[StoredThread]:
        q = (
            graph_threads.select()
            .where(mine(graph_threads), team_visible(graph_threads))
            .order_by(graph_threads.c.updated_at.desc(), graph_threads.c.id)
        )
        if graph:
            q = q.where(graph_threads.c.graph == graph)
        async with self.tx() as c:
            return await rows(c, q, StoredThread)

    async def threads(self, graph: str | None) -> list[dict[str, Any]]:
        """`thread_rows` as mappings, for the callers that still read a thread by key."""
        return [r.model_dump() for r in await self.thread_rows(graph)]

    async def thread_page(
        self, graph: str, labels: Mapping[str, str], other: str, wanted: Sequence[str], *, offset: int, limit: int
    ) -> tuple[list[RunThread], int, dict[str, int]]:
        """One page of `graph`'s threads, newest update first then by id, with the total and the count per label.
        `labels` names a thread status's label and `other` every status it does not name; `wanted` keeps the threads
        whose label it lists (all when empty). The counts leave `wanted` out, so a filtered list still counts each."""
        status = graph_threads.c.status
        scope = (graph_threads.c.graph == graph, mine(graph_threads), team_visible(graph_threads))
        counted: dict[str, int] = {}
        chosen: list[sa.ColumnElement[bool]] = []
        if wanted:
            named = [raw for raw, label in labels.items() if label in wanted]
            chosen = [sa.or_(status.in_(named), *([status.not_in(list(labels))] if other in wanted else []))]
        t = graph_threads.c
        page = (
            sa.select(t.id, t.status, t.version, t.meta, t.created_at, t.updated_at)
            .where(*scope, *chosen)
            .order_by(graph_threads.c.updated_at.desc(), graph_threads.c.id)
            .offset(offset)
            .limit(limit)
        )
        async with self.tx() as c:
            for raw, n in await c.execute(sa.select(status, sa.func.count()).where(*scope).group_by(status)):
                label = labels.get(str(raw), other)
                counted[label] = counted.get(label, 0) + int(n)
            total = int(
                (
                    await c.execute(sa.select(sa.func.count()).select_from(graph_threads).where(*scope, *chosen))
                ).scalar_one()
            )
            found = await rows(c, page, RunThread)
        return found, total, counted

    async def run_events(self, thread_ids: Sequence[str]) -> list[RunJournal]:
        """The named threads' runs' kinds and events, oldest run first, in one statement."""
        if not thread_ids:
            return []
        q = (
            sa.select(graph_runs.c.thread_id, graph_runs.c.kind, graph_runs.c.events)
            .where(graph_runs.c.thread_id.in_(list(thread_ids)), mine(graph_runs), team_visible(graph_runs))
            .order_by(graph_runs.c.created_at, graph_runs.c.id)
        )
        async with self.tx() as c:
            return await rows(c, q, RunJournal)

    async def set_thread_status(self, thread_id: str, status: str, now: str, *, generation: int | None = None) -> None:
        """`generation`: the writing run's lease generation, checked in this transaction (ADR-0016)."""

        async with self.tx() as c:
            await check_fence(c, thread_id, generation)
            await c.execute(
                graph_threads.update().where(graph_threads.c.id == thread_id).values(status=status, updated_at=now)
            )

    async def run(self, run_id: str) -> RunRow | None:
        q = sa.select(graph_runs).where(graph_runs.c.id == run_id, mine(graph_runs), team_visible(graph_runs))
        async with self.tx() as c:
            return await one(c, q, RunRow)

    async def runs(self, thread_id: str) -> list[RunRow]:
        q = (
            sa.select(graph_runs)
            .where(graph_runs.c.thread_id == thread_id, mine(graph_runs), team_visible(graph_runs))
            .order_by(graph_runs.c.created_at, graph_runs.c.id)
        )
        async with self.tx() as c:
            return await rows(c, q, RunRow)

    async def mark_crashed(
        self,
        run_id: str,
        now: str,
        *,
        owner: str | None = None,
        running: list[str] | None = None,
        generation: int | None = None,
        by_generation: int | None = None,
    ) -> None:
        """The run's process died holding the lease: interrupted by a crash, recorded before the recovery starts. The
        dead run wrote no events (they are written at the end), so the sweeper records who owned it, which nodes were
        running when it died and its generation, from the lease and the last checkpoint. `by_generation` is the
        sweeper's own new generation, checked in this transaction."""

        crashed = {
            "event": "crashed",
            "data": {"owner": owner, "running": running or [], "generation": generation, "at": now},
        }
        async with self.tx() as c:
            row = (
                await c.execute(
                    sa.select(graph_runs.c.events, graph_runs.c.thread_id).where(
                        graph_runs.c.id == run_id, team_visible(graph_runs)
                    )
                )
            ).first()
            if row is None:
                return
            await check_fence(c, row.thread_id, by_generation)
            await c.execute(
                graph_runs.update()
                .where(graph_runs.c.id == run_id, graph_runs.c.status == "running")
                .values(status="crashed", finished_at=now, events=[*row.events, crashed])
            )

    async def start_run(
        self, run_id: str, thread_id: str, kind: str, now: str, run_input: Any = None, *, generation: int | None = None
    ) -> bool:
        """Records the run; False when the id already exists (the caller replays or refuses). `generation` is the
        run's lease generation, checked in this transaction (ADR-0016)."""

        async with self.tx() as c:
            await check_fence(c, thread_id, generation)
            taken = sa.select(graph_runs.c.id).where(graph_runs.c.id == run_id, team_visible(graph_runs))
            if (await c.execute(taken)).first():
                return False
            owner = graph_threads.c.team_id
            team = (
                sa.select(owner).where(graph_threads.c.id == thread_id, team_visible(graph_threads)).scalar_subquery()
            )
            await c.execute(
                graph_runs.insert().values(
                    id=run_id,
                    thread_id=thread_id,
                    kind=kind,
                    status="running",
                    events=[],
                    created_at=now,
                    input=run_input,
                    team_id=team,
                )
            )
            return True

    async def finish_run(
        self, run_id: str, status: str, events: list[Json], now: str, *, generation: int | None = None
    ) -> None:
        """Records how a run ended. A run that lost its thread (the sweeper marked it crashed, or its lease generation
        is no longer current) keeps the status and crash record the new owner wrote: its own events are appended under
        a `stale_owner_finished` event instead of replacing them (ADR-0016)."""
        from ops_checkpointer import LeaseSupersededError  # noqa: PLC0415

        async with self.tx() as c:
            q = sa.select(graph_runs.c.events, graph_runs.c.thread_id, graph_runs.c.status).where(
                graph_runs.c.id == run_id, team_visible(graph_runs)
            )
            row = (await c.execute(q)).first()
            if row is None:
                return
            stale = row.status == "crashed"
            if not stale:
                try:
                    await check_fence(c, row.thread_id, generation)
                except LeaseSupersededError:
                    stale = True
            if not stale:
                await c.execute(
                    graph_runs.update()
                    .where(graph_runs.c.id == run_id)
                    .values(status=status, events=events, finished_at=now)
                )
                return
            late = {"event": "stale_owner_finished", "data": {"status": status, "at": now, "events": events}}
            await c.execute(graph_runs.update().where(graph_runs.c.id == run_id).values(events=[*row.events, late]))

    async def meta(self, thread_id: str) -> Json:
        async with self.tx() as c:
            meta: object = (
                await c.execute(
                    sa.select(graph_threads.c.meta).where(graph_threads.c.id == thread_id, team_visible(graph_threads))
                )
            ).scalar_one_or_none()
        return dict(narrow.an_object(meta or {}, "thread meta"))

    async def set_overrides(self, thread_id: str, overrides: Json | None, *, updated_at: str) -> None:
        """Replaces the thread's overrides; the caller has checked them against the agent's limits."""
        async with self.tx() as c:
            await c.execute(
                graph_threads.update()
                .where(graph_threads.c.id == thread_id, mine(graph_threads))
                .values(overrides=overrides, updated_at=updated_at)
            )

    async def set_deployment(self, thread_id: str, deployment_id: str) -> None:
        """Marks a thread as started on a deployment (an embed), so its usage is counted on the column."""
        async with self.tx() as c:
            await c.execute(
                graph_threads.update().where(graph_threads.c.id == thread_id).values(deployment_id=deployment_id)
            )

    async def deployment_usage(self, teams: dict[str, str], since: str) -> dict[str, tuple[int, str | None]]:
        """Per deployment id in `teams` (id -> owning team): threads started on it at or after `since`, and when one
        last changed. Counted in the deployment's own team only, in one grouped query."""
        if not teams:
            return {}
        t = graph_threads
        recent = sa.func.sum(sa.case((t.c.created_at >= since, 1), else_=0))
        q = (
            sa.select(t.c.deployment_id, t.c.team_id, recent, sa.func.max(t.c.updated_at))
            .where(t.c.deployment_id.in_(list(teams)), team_visible(t))
            .group_by(t.c.deployment_id, t.c.team_id)
        )
        async with self.tx() as c:
            rows = (await c.execute(q)).all()
        return {str(d): (int(n or 0), last) for d, team, n, last in rows if teams.get(str(d)) == team}

    async def merge_meta(
        self, thread_id: str, patch: Json, *, updated_at: str | None = None, lock: bool = False
    ) -> None:
        """Merges `patch` into the thread's meta. `lock` takes the row lock for the read and write, so two locked
        patches do not lose one another; it waits on any transaction that holds the row, so a caller inside one
        must not pass it."""
        async with self.tx() as c:
            q = sa.select(graph_threads.c.meta).where(graph_threads.c.id == thread_id, team_visible(graph_threads))
            if lock:
                q = locked(q, graph_threads)
            meta: object = (await c.execute(q)).scalar_one_or_none()
            merged: Json = {**narrow.an_object(meta or {}, "thread meta"), **patch}
            update = (
                graph_threads.update()
                .where(graph_threads.c.id == thread_id)
                .values(meta=merged, owner=_owner(merged.get("ownerEmail")))
            )
            if updated_at is not None:
                update = update.values(updated_at=updated_at)
            await c.execute(update)

    async def thread_ids(self, graph: str, version: int, statuses: tuple[str, ...]) -> list[str]:
        q = sa.select(graph_threads.c.id).where(
            graph_threads.c.graph == graph,
            graph_threads.c.version == version,
            graph_threads.c.status.in_(statuses),
            mine(graph_threads),
            team_visible(graph_threads),
        )
        async with self.tx() as c:
            return [str(r[0]) for r in await c.execute(q)]

    async def latest_versions(self) -> dict[str, int]:
        """Every published definition's name and its highest version."""
        q = (
            sa.select(graph_versions.c.name, sa.func.max(graph_versions.c.version))
            .where(mine(graph_versions))
            .group_by(graph_versions.c.name)
        )
        async with self.tx() as c:
            return {str(r[0]): int(r[1]) for r in await c.execute(q)}

    async def run_summaries(self, only: str | None = None) -> dict[str, list[RunSummary]]:
        """Every run's kind, status, input and finish, without its events, by thread, oldest first."""
        q = (
            sa.select(
                graph_runs.c.thread_id,
                graph_runs.c.kind,
                graph_runs.c.status,
                graph_runs.c.input,
                graph_runs.c.finished_at,
            )
            .where(mine(graph_runs), team_visible(graph_runs))
            .order_by(graph_runs.c.created_at, graph_runs.c.id)
        )
        if only is not None:
            q = q.where(graph_runs.c.thread_id == only)
        out: dict[str, list[RunSummary]] = {}
        async with self.tx() as c:
            for r in await rows(c, q, RunSummary):
                out.setdefault(r.thread_id, []).append(r)
        return out

    async def agent_threads_since(self, since: str) -> list[tuple[str, Json]]:
        """(graph, meta) of every agent_wrapper and agent:<id> thread created at or after `since`."""
        q = sa.select(graph_threads.c.graph, graph_threads.c.meta).where(
            sa.or_(graph_threads.c.graph == "agent_wrapper", graph_threads.c.graph.like("agent:%")),
            graph_threads.c.created_at >= since,
            mine(graph_threads),
            team_visible(graph_threads),
        )
        async with self.tx() as c:
            return [(str(g), dict(narrow.an_object(m or {}, "thread meta"))) for g, m in await c.execute(q)]

    async def thread_stats(self) -> list[tuple[str, str, str]]:
        """(graph, status, created at) of every thread."""
        q = sa.select(graph_threads.c.graph, graph_threads.c.status, graph_threads.c.created_at).where(
            mine(graph_threads), team_visible(graph_threads)
        )
        async with self.tx() as c:
            return [(str(g), str(s), str(t)) for g, s, t in await c.execute(q)]
