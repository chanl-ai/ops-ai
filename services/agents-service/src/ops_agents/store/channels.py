"""Tables for channels and deployments (E6): what a deployment runs, which inbound messages it has seen, where its
delta sync stands, replies waiting on a thread, and attachment bytes kept out of graph state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import Guarantee
from ops_store.team_scope import team_visible

from .base import metadata
from .graphs import graph_threads
from .tenancy import tenant_tx

Multitask = Literal["enqueue", "reject"]

deployments = sa.Table(
    "deployments",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("graph", sa.String(64), nullable=False),
    sa.Column("channel", sa.String(32), nullable=False),
    # A paused deployment opens no new cases; replies to its existing cases still arrive.
    sa.Column("paused", sa.Boolean, nullable=False, server_default=sa.false()),
    # What a message for a thread that is mid-run does: wait its turn (enqueue) or be refused (reject).
    sa.Column("multitask", sa.String(16), nullable=False, server_default="enqueue"),
    sa.Column("created_at", sa.String(32), nullable=False),
    # Default budget for each case it opens: {"max_calls", "max_tokens", "max_cost"} (E12).
    sa.Column("budget", sa.JSON(), nullable=True),
    # The team that owns the deployment; empty when none does, which only an admin changes (c-115).
    sa.Column("team_id", sa.String(64), nullable=False, server_default=""),
)

channel_messages = sa.Table(
    "channel_messages",
    metadata,
    sa.Column("deployment_id", sa.String(64), primary_key=True),
    # Normalised Message-ID, or a synthetic key when the message has none.
    sa.Column("message_key", sa.String(512), primary_key=True),
    sa.Column("thread_id", sa.String(64)),
    sa.Column("role", sa.String(16), nullable=False),
    # handled, or deferred (a new case while the deployment was paused; retried on the next poll).
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("payload", sa.JSON),
    sa.Column("received_at", sa.String(32), nullable=False),
)

channel_cursors = sa.Table(
    "channel_cursors",
    metadata,
    sa.Column("deployment_id", sa.String(64), primary_key=True),
    sa.Column("delta_link", sa.Text, nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
)

thread_inbox = sa.Table(
    "thread_inbox",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("message_key", sa.String(512), primary_key=True),
    sa.Column("seq", sa.BigInteger, nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    # queued (the thread was mid-run) or delivered.
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("delivered_at", sa.String(32)),
)

channel_files = sa.Table(
    "channel_files",
    metadata,
    sa.Column("file_id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(512), nullable=False),
    sa.Column("content_type", sa.String(128), nullable=False),
    sa.Column("size", sa.Integer, nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False),
    # The files service stub: the bytes as text. Graph state carries only the file id (E4).
    sa.Column("content", sa.Text, nullable=False),
)


@dataclass(frozen=True)
class Deployment:
    id: str
    graph: str
    channel: str
    paused: bool
    multitask: Multitask
    budget: dict[str, Any] | None = None
    team_id: str = ""


class ChannelStore:
    # A channel message is recorded once by its provider id and a cursor moves only forward (CAS); a delivery decides
    # and writes in one transaction (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def _insert(self, table: sa.Table) -> Any:
        return (postgresql.insert if self.engine.dialect.name == "postgresql" else sqlite.insert)(table)

    async def put_deployment(self, d: Deployment, now: str) -> None:
        values = {
            "graph": d.graph,
            "channel": d.channel,
            "paused": d.paused,
            "multitask": d.multitask,
            "budget": d.budget,
            "team_id": d.team_id,
        }
        stmt = (
            self._insert(deployments)
            .values(id=d.id, created_at=now, **values)
            .on_conflict_do_update(index_elements=["id"], set_=values)
        )
        async with self.engine.begin() as c:
            await c.execute(stmt)

    async def deployment(self, deployment_id: str) -> Deployment | None:
        async with self.engine.connect() as c:
            r = (await c.execute(deployments.select().where(deployments.c.id == deployment_id))).mappings().first()
        if r is None:
            return None
        return Deployment(r["id"], r["graph"], r["channel"], r["paused"], r["multitask"], r["budget"], r["team_id"])

    async def set_paused(self, deployment_id: str, paused: bool) -> bool:
        async with self.engine.begin() as c:
            res = await c.execute(deployments.update().where(deployments.c.id == deployment_id).values(paused=paused))
            return res.rowcount == 1

    # ── the message ledger ──

    async def seen(self, deployment_id: str, keys: list[str]) -> dict[str, dict[str, Any]]:
        if not keys:
            return {}
        q = channel_messages.select().where(
            channel_messages.c.deployment_id == deployment_id, channel_messages.c.message_key.in_(keys)
        )
        async with self.engine.connect() as c:
            return {r["message_key"]: dict(r) for r in (await c.execute(q)).mappings()}

    async def record(
        self,
        deployment_id: str,
        key: str,
        *,
        thread_id: str | None,
        role: str,
        status: str,
        now: str,
        payload: Any = None,
    ) -> None:
        values = {"thread_id": thread_id, "role": role, "status": status, "payload": payload}
        stmt = (
            self._insert(channel_messages)
            .values(deployment_id=deployment_id, message_key=key, received_at=now, **values)
            .on_conflict_do_update(index_elements=["deployment_id", "message_key"], set_=values)
        )
        async with self.engine.begin() as c:
            await c.execute(stmt)

    async def deferred(self, deployment_id: str) -> list[dict[str, Any]]:
        q = (
            channel_messages.select()
            .where(channel_messages.c.deployment_id == deployment_id, channel_messages.c.status == "deferred")
            .order_by(channel_messages.c.received_at)
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    # ── delta cursor ──

    async def cursor(self, deployment_id: str) -> str | None:
        async with self.engine.connect() as c:
            q = sa.select(channel_cursors.c.delta_link).where(channel_cursors.c.deployment_id == deployment_id)
            return (await c.execute(q)).scalar_one_or_none()

    async def save_cursor(self, deployment_id: str, delta_link: str, now: str) -> None:
        stmt = (
            self._insert(channel_cursors)
            .values(deployment_id=deployment_id, delta_link=delta_link, updated_at=now)
            .on_conflict_do_update(index_elements=["deployment_id"], set_={"delta_link": delta_link, "updated_at": now})
        )
        async with self.engine.begin() as c:
            await c.execute(stmt)

    # ── thread inbox ──

    async def add_to_inbox(
        self, c: AsyncConnection, thread_id: str, key: str, *, kind: str, payload: Any, status: str, now: str
    ) -> tuple[str, int]:
        """Adds a message to the thread's inbox once; a redelivery returns the first entry's status and position."""
        existing = (
            await c.execute(
                sa.select(thread_inbox.c.status, thread_inbox.c.seq).where(
                    thread_inbox.c.thread_id == thread_id, thread_inbox.c.message_key == key
                )
            )
        ).first()
        if existing is not None:
            return str(existing.status), int(existing.seq)
        seq = (
            int(
                (
                    await c.execute(
                        sa.select(sa.func.coalesce(sa.func.max(thread_inbox.c.seq), 0)).where(
                            thread_inbox.c.thread_id == thread_id
                        )
                    )
                ).scalar_one()
            )
            + 1
        )
        await c.execute(
            thread_inbox.insert().values(
                thread_id=thread_id,
                message_key=key,
                seq=seq,
                kind=kind,
                payload=payload,
                status=status,
                created_at=now,
                delivered_at=now if status == "delivered" else None,
            )
        )
        return status, seq

    async def thread_for_key(self, external_key: str) -> str | None:
        """The case opened for a message, as soon as it exists: find-or-create writes it before the first run starts,
        while the ledger is written only after the message is handled."""
        q = sa.select(graph_threads.c.id).where(
            graph_threads.c.external_key == external_key, team_visible(graph_threads)
        )
        async with tenant_tx(self.engine) as c:
            found: Any = (await c.execute(q)).scalar_one_or_none()
        return str(found) if found is not None else None

    async def inbox(self, thread_id: str) -> list[dict[str, Any]]:
        q = thread_inbox.select().where(thread_inbox.c.thread_id == thread_id).order_by(thread_inbox.c.seq)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def deliver_queued(self, thread_id: str, now: str) -> list[int]:
        """Marks the thread's queued messages delivered, in arrival order. Returns their positions."""
        async with self.engine.begin() as c:
            q = (
                sa.select(thread_inbox.c.seq)
                .where(thread_inbox.c.thread_id == thread_id, thread_inbox.c.status == "queued")
                .order_by(thread_inbox.c.seq)
            )
            seqs = [int(r.seq) for r in await c.execute(q)]
            if seqs:
                await c.execute(
                    thread_inbox.update()
                    .where(thread_inbox.c.thread_id == thread_id, thread_inbox.c.seq.in_(seqs))
                    .values(status="delivered", delivered_at=now)
                )
            return seqs

    # ── files stub ──

    async def put_file(self, file_id: str, *, name: str, content_type: str, content: str, sha256: str) -> None:
        stmt = (
            self._insert(channel_files)
            .values(
                file_id=file_id, name=name, content_type=content_type, size=len(content), sha256=sha256, content=content
            )
            .on_conflict_do_nothing(index_elements=["file_id"])
        )
        async with self.engine.begin() as c:
            await c.execute(stmt)

    async def read_file(self, file_id: str) -> str:
        async with self.engine.connect() as c:
            q = sa.select(channel_files.c.content).where(channel_files.c.file_id == file_id)
            return str((await c.execute(q)).scalar_one())
