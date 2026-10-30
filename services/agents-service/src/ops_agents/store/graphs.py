"""Graph threads, versions and runs (SQLAlchemy Core, no ORM). Console chat is a facade over these threads and the
event log (chat_threads.py); its own tables were dropped in migration 0017.

Column types are the portable ones (JSON, not JSONB) so the API tests run on SQLite and production on PostgreSQL.
"""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import Guarantee
from ops_store.dialect import insert_ignore, locked
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import any_team, team_visible

from .base import metadata
from .leases import check_fence
from .tenancy import CLAIM_THREAD, current_tenant, system_tx, tenant_tx

graph_threads = sa.Table(
    "graph_threads",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("graph", sa.String(64), nullable=False, index=True),
    sa.Column("meta", sa.JSON, nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
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
    # A chat thread's overrides within its agent's limits, applied to every turn (c-071; activities/overrides.py).
    sa.Column("overrides", sa.JSON),
    # Set from the request's or loop's tenant (store/tenancy.py), never from a body; PostgreSQL RLS reads it (0021).
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    # Per tenant, so one tenant's key neither collides with nor reveals another's.
    sa.UniqueConstraint("tenant_id", "external_key", name="uq_graph_threads_tenant_external_key"),
    # A team's thread list, newest first (c-280).
    sa.Index("ix_graph_threads_team_updated", "tenant_id", "team_id", "updated_at"),
    # Held to the caller's team by the database too (c-429, migration 0073): another team's thread is not found.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

graph_versions = sa.Table(
    "graph_versions",
    metadata,
    sa.Column("name", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("digest", sa.String(64), nullable=False, unique=True),
    sa.Column("definition", sa.JSON, nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
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
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    # The thread's team, copied when the run starts, so the policy holds the run without reading its thread.
    sa.Column("team_id", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


def _mine(table: sa.Table) -> sa.ColumnElement[bool]:
    """The tenant filter in the query itself, for SQLite; on PostgreSQL RLS applies it as well."""
    return table.c.tenant_id == current_tenant()


class GraphStore:
    # Run and status writes are checked against the lease generation in their own transaction (TRANSACTION); a
    # thread found or created by external key, and a version stored once per digest, rest on unique inserts (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def create_thread(
        self,
        thread_id: str,
        graph: str,
        meta: dict[str, Any],
        team_id: str,
        now: str,
        *,
        version: int | None = None,
        digest: str | None = None,
    ) -> None:
        async with tenant_tx(self.engine) as c:
            await c.execute(
                graph_threads.insert().values(
                    id=thread_id,
                    graph=graph,
                    meta=meta,
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
        async with system_tx(self.engine, CLAIM_THREAD) as c:
            q = sa.select(t.c.tenant_id, t.c.team_id).where(t.c.id == thread_id, any_team(t, "a loop finds its owner"))
            row = (await c.execute(q)).first()
        return (str(row[0]), str(row[1])) if row else None

    async def thread_by_key(self, external_key: str) -> dict[str, Any] | None:
        async with tenant_tx(self.engine) as c:
            q = graph_threads.select().where(
                graph_threads.c.external_key == external_key, _mine(graph_threads), team_visible(graph_threads)
            )
            row = (await c.execute(q)).mappings().first()
        return dict(row) if row else None

    async def find_or_create_thread(
        self,
        thread_id: str,
        graph: str,
        meta: dict[str, Any],
        team_id: str,
        now: str,
        *,
        external_key: str,
        deployment_id: str | None = None,
        parent_thread_id: str | None = None,
        version: int | None = None,
        digest: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """The thread for `external_key`, created when there is none, in one transaction: the insert either wins or
        conflicts on the unique key, and the conflict path reads the existing row. Returns (row, created)."""
        values = {
            "id": thread_id,
            "graph": graph,
            "meta": meta,
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
        async with tenant_tx(self.engine) as c:
            stmt = insert_ignore(c, graph_threads, values, keys=["tenant_id", "external_key"])
            created = (await c.execute(stmt)).rowcount == 1
            row = (
                (
                    await c.execute(
                        graph_threads.select().where(
                            graph_threads.c.external_key == external_key,
                            _mine(graph_threads),
                            team_visible(graph_threads),
                        )
                    )
                )
                .mappings()
                .one()
            )
        return dict(row), created

    async def pin(self, thread_id: str, version: int, digest: str, now: str) -> None:
        async with tenant_tx(self.engine) as c:
            await c.execute(
                graph_threads.update()
                .where(graph_threads.c.id == thread_id)
                .values(version=version, digest=digest, updated_at=now)
            )

    async def versions(self, name: str) -> list[dict[str, Any]]:
        q = graph_versions.select().where(graph_versions.c.name == name).order_by(graph_versions.c.version)
        async with self.engine.begin() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def version(self, name: str, version: int) -> dict[str, Any] | None:
        q = graph_versions.select().where(graph_versions.c.name == name, graph_versions.c.version == version)
        async with self.engine.begin() as c:
            row = (await c.execute(q)).mappings().first()
        return dict(row) if row else None

    async def publish(self, name: str, definition: dict[str, Any], digest: str, now: str) -> int:
        """Stores the next version of a workflow; a definition already stored under its digest returns that version."""
        async with self.engine.begin() as c:
            same = (
                await c.execute(sa.select(graph_versions.c.version).where(graph_versions.c.digest == digest))
            ).first()
            if same:
                return int(same.version)
            latest = (
                await c.execute(sa.select(sa.func.max(graph_versions.c.version)).where(graph_versions.c.name == name))
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

    async def thread(self, thread_id: str) -> dict[str, Any] | None:
        async with tenant_tx(self.engine) as c:
            row = (
                (
                    await c.execute(
                        graph_threads.select().where(
                            graph_threads.c.id == thread_id, _mine(graph_threads), team_visible(graph_threads)
                        )
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def threads(self, graph: str | None) -> list[dict[str, Any]]:
        q = (
            graph_threads.select()
            .where(_mine(graph_threads), team_visible(graph_threads))
            .order_by(graph_threads.c.updated_at.desc())
        )
        if graph:
            q = q.where(graph_threads.c.graph == graph)
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def set_thread_status(self, thread_id: str, status: str, now: str, *, generation: int | None = None) -> None:
        """`generation`: the writing run's lease generation, checked in this transaction (ADR-0016)."""

        async with tenant_tx(self.engine) as c:
            await check_fence(c, thread_id, generation)
            await c.execute(
                graph_threads.update().where(graph_threads.c.id == thread_id).values(status=status, updated_at=now)
            )

    async def run(self, run_id: str) -> dict[str, Any] | None:
        async with tenant_tx(self.engine) as c:
            row = (
                (
                    await c.execute(
                        graph_runs.select().where(
                            graph_runs.c.id == run_id, _mine(graph_runs), team_visible(graph_runs)
                        )
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def runs(self, thread_id: str) -> list[dict[str, Any]]:
        q = (
            graph_runs.select()
            .where(graph_runs.c.thread_id == thread_id, _mine(graph_runs), team_visible(graph_runs))
            .order_by(graph_runs.c.created_at)
        )
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

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
        async with tenant_tx(self.engine) as c:
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

        async with tenant_tx(self.engine) as c:
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
        self, run_id: str, status: str, events: list[dict[str, Any]], now: str, *, generation: int | None = None
    ) -> None:
        """Records how a run ended. A run that lost its thread (the sweeper marked it crashed, or its lease generation
        is no longer current) keeps the status and crash record the new owner wrote: its own events are appended under
        a `stale_owner_finished` event instead of replacing them (ADR-0016)."""
        from ops_checkpointer import LeaseSupersededError  # noqa: PLC0415

        async with tenant_tx(self.engine) as c:
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

    async def meta(self, thread_id: str) -> dict[str, Any]:
        async with tenant_tx(self.engine) as c:
            meta: Any = (
                await c.execute(
                    sa.select(graph_threads.c.meta).where(graph_threads.c.id == thread_id, team_visible(graph_threads))
                )
            ).scalar_one_or_none()
        return dict(meta or {})

    async def set_overrides(self, thread_id: str, overrides: dict[str, Any] | None, *, updated_at: str) -> None:
        """Replaces the thread's overrides; the caller has checked them against the agent's limits."""
        async with tenant_tx(self.engine) as c:
            await c.execute(
                graph_threads.update()
                .where(graph_threads.c.id == thread_id, _mine(graph_threads))
                .values(overrides=overrides, updated_at=updated_at)
            )

    async def set_deployment(self, thread_id: str, deployment_id: str) -> None:
        """Marks a thread as started on a deployment (an embed, c-130), so its usage is counted on the column."""
        async with tenant_tx(self.engine) as c:
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
        async with tenant_tx(self.engine) as c:
            rows = (await c.execute(q)).all()
        return {str(d): (int(n or 0), last) for d, team, n, last in rows if teams.get(str(d)) == team}

    async def merge_meta(
        self, thread_id: str, patch: dict[str, Any], *, updated_at: str | None = None, lock: bool = False
    ) -> None:
        """Merges `patch` into the thread's meta. `lock` takes the row lock for the read and write, so two locked
        patches do not lose one another; it waits on any transaction that holds the row, so a caller inside one
        must not pass it."""
        async with tenant_tx(self.engine) as c:
            q = sa.select(graph_threads.c.meta).where(graph_threads.c.id == thread_id, team_visible(graph_threads))
            if lock:
                q = locked(q, graph_threads)
            meta: Any = (await c.execute(q)).scalar_one_or_none()
            values: dict[str, Any] = {"meta": {**(meta or {}), **patch}}
            if updated_at is not None:
                values["updated_at"] = updated_at
            await c.execute(graph_threads.update().where(graph_threads.c.id == thread_id).values(**values))

    async def thread_ids(self, graph: str, version: int, statuses: tuple[str, ...]) -> list[str]:
        q = sa.select(graph_threads.c.id).where(
            graph_threads.c.graph == graph,
            graph_threads.c.version == version,
            graph_threads.c.status.in_(statuses),
            _mine(graph_threads),
            team_visible(graph_threads),
        )
        async with tenant_tx(self.engine) as c:
            return [str(r[0]) for r in await c.execute(q)]

    async def latest_versions(self) -> dict[str, int]:
        """Every published definition's name and its highest version."""
        q = sa.select(graph_versions.c.name, sa.func.max(graph_versions.c.version)).group_by(graph_versions.c.name)
        async with self.engine.begin() as c:
            return {str(r[0]): int(r[1]) for r in await c.execute(q)}

    async def run_summaries(self, only: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """Every run's kind, status, input and finish, without its events, by thread, oldest first."""
        q = (
            sa.select(
                graph_runs.c.thread_id,
                graph_runs.c.kind,
                graph_runs.c.status,
                graph_runs.c.input,
                graph_runs.c.finished_at,
            )
            .where(_mine(graph_runs), team_visible(graph_runs))
            .order_by(graph_runs.c.created_at)
        )
        if only is not None:
            q = q.where(graph_runs.c.thread_id == only)
        out: dict[str, list[dict[str, Any]]] = {}
        async with tenant_tx(self.engine) as c:
            for r in (await c.execute(q)).mappings():
                out.setdefault(str(r["thread_id"]), []).append(dict(r))
        return out

    async def agent_threads_since(self, since: str) -> list[tuple[str, dict[str, Any]]]:
        """(graph, meta) of every agent_wrapper and agent:<id> thread created at or after `since`."""
        q = sa.select(graph_threads.c.graph, graph_threads.c.meta).where(
            sa.or_(graph_threads.c.graph == "agent_wrapper", graph_threads.c.graph.like("agent:%")),
            graph_threads.c.created_at >= since,
            _mine(graph_threads),
            team_visible(graph_threads),
        )
        async with tenant_tx(self.engine) as c:
            return [(str(g), dict(m or {})) for g, m in await c.execute(q)]

    async def thread_stats(self) -> list[tuple[str, str, str]]:
        """(graph, status, created at) of every thread."""
        q = sa.select(graph_threads.c.graph, graph_threads.c.status, graph_threads.c.created_at).where(
            _mine(graph_threads), team_visible(graph_threads)
        )
        async with tenant_tx(self.engine) as c:
            return [(str(g), str(s), str(t)) for g, s, t in await c.execute(q)]
