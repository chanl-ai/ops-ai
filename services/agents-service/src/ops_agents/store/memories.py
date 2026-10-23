"""What agents remember about each person (c-124): keyed by person and agent, never by conversation, so a memory
follows the person into their next chat with that agent and no one else's."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import any_team, team_visible

from .base import metadata
from .tenancy import RETENTION_TENANTS, current_tenant, system_tx, tenant_tx

agent_memories = sa.Table(
    "agent_memories",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, index=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("agent_id", sa.String(64), nullable=False),
    # The person's id from their token (Principal.sub, else their email): the key every read is scoped by.
    sa.Column("person", sa.String(320), nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("key", sa.String(120)),
    sa.Column("value", sa.String(2000), nullable=False),
    sa.Column("confidence", sa.Float(), nullable=False),
    # extraction (from a chat turn) or person (a correction they made).
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("source_thread_id", sa.String(64)),
    sa.Column("created_at", sa.String(32), nullable=False),
    # Set when a newer value for the same key replaced it; kept for the record, never loaded.
    sa.Column("superseded_at", sa.String(32)),
    sa.Index("ix_agent_memories_owner", "tenant_id", "person", "agent_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

memory_audit = sa.Table(
    "memory_audit",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, index=True),
    sa.Column("person", sa.String(320), nullable=False),
    sa.Column("agent_id", sa.String(64), nullable=False),
    sa.Column("memory_id", sa.String(64)),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("actor", sa.String(320), nullable=False),
    sa.Column("at", sa.String(32), nullable=False),
    info=TENANT_SCOPED,
)


# Background process (docs/architecture/identity-and-tenancy.md, "The team is the workspace"): the workspace retention
# policy deletes every team's old memories of a tenant.
RETENTION = "background process: memory retention reads every team's memories of its tenant"


class Memories:
    # A save supersedes the current row for its key and inserts the new one in one transaction, so two saves of the
    # same key leave one current value; a forget deletes and audits together.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def _mine(self, person: str, agent_id: str | None) -> list[Any]:
        m = agent_memories.c
        where = [m.tenant_id == current_tenant(), m.person == person]
        return [*where, m.agent_id == agent_id] if agent_id else where

    async def save(
        self,
        *,
        team_id: str,
        agent_id: str,
        person: str,
        kind: str,
        key: str | None,
        value: str,
        confidence: float,
        source: str,
        thread_id: str | None,
    ) -> dict[str, Any]:
        m, now = agent_memories, now_iso()
        row = {
            "id": new_id("mem"),
            "team_id": team_id,
            "agent_id": agent_id,
            "person": person,
            "kind": kind,
            "key": key,
            "value": value,
            "confidence": confidence,
            "source": source,
            "source_thread_id": thread_id,
            "created_at": now,
            "superseded_at": None,
        }
        async with tenant_tx(self.engine) as c:
            if key:
                await c.execute(
                    m.update()
                    .where(*self._mine(person, agent_id), m.c.key == key, m.c.superseded_at.is_(None))
                    .values(superseded_at=now)
                )
            await c.execute(m.insert().values(**row))
        return row

    async def current(self, person: str, agent_id: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
        """The person's memories not superseded, newest first; with `agent_id`, that agent's only."""
        m = agent_memories
        q = (
            sa.select(m)
            .where(*self._mine(person, agent_id), team_visible(m), m.c.superseded_at.is_(None))
            .order_by(m.c.created_at.desc())
            .limit(limit)
        )
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def search(self, person: str, agent_id: str, words: list[str], *, limit: int = 10) -> list[dict[str, Any]]:
        """Current memories of this person with this agent whose key or value holds every word (case ignored)."""
        m = agent_memories
        conds = [
            sa.or_(sa.func.lower(m.c.value).contains(w.lower()), sa.func.lower(m.c.key).contains(w.lower()))
            for w in words
        ]
        q = (
            sa.select(m)
            .where(*self._mine(person, agent_id), team_visible(m), m.c.superseded_at.is_(None), *conds)
            .order_by(m.c.created_at.desc())
            .limit(limit)
        )
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def supersede(self, person: str, memory_id: str) -> None:
        """Marks one of the person's memories replaced: a corrected episode, which has no key to supersede by."""
        m = agent_memories
        async with tenant_tx(self.engine) as c:
            await c.execute(
                m.update().where(*self._mine(person, None), m.c.id == memory_id).values(superseded_at=now_iso())
            )

    async def get(self, person: str, memory_id: str) -> dict[str, Any] | None:
        m = agent_memories
        async with tenant_tx(self.engine) as c:
            r = (
                (await c.execute(sa.select(m).where(*self._mine(person, None), team_visible(m), m.c.id == memory_id)))
                .mappings()
                .first()
            )
        return dict(r) if r else None

    async def forget(
        self, person: str, *, actor: str, agent_id: str | None = None, memory_id: str | None = None
    ) -> int:
        """Deletes one memory, or all of the person's with an agent (every version, superseded ones included), and
        audits each in the same transaction. The number deleted."""
        m, now = agent_memories, now_iso()
        where = self._mine(person, agent_id)
        if memory_id:
            current = await self.get(person, memory_id)
            if current is None:
                return 0
            # Its older versions go too, so nothing the person asked to forget stays in the table.
            where = [
                *self._mine(person, current["agent_id"]),
                sa.or_(m.c.id == memory_id, sa.and_(m.c.key.is_not(None), m.c.key == current["key"])),
            ]
        async with tenant_tx(self.engine) as c:
            rows = (await c.execute(sa.select(m.c.id, m.c.agent_id).where(*where))).all()
            if not rows:
                return 0
            await c.execute(m.delete().where(m.c.id.in_([r.id for r in rows])))
            await c.execute(
                memory_audit.insert(),
                [
                    {
                        "id": new_id("mau"),
                        "person": person,
                        "agent_id": r.agent_id,
                        "memory_id": r.id,
                        "action": "forget",
                        "actor": actor,
                        "at": now,
                    }
                    for r in rows
                ],
            )
        return len(rows)

    async def expire(self, before: str, *, actor: str) -> int:
        """Deletes the tenant's memories saved before `before` (every person and agent) and audits each as `expire` in
        the same transaction, for the workspace retention policy. The number deleted."""
        m = agent_memories
        async with tenant_tx(self.engine) as c:
            q = sa.select(m.c.id, m.c.agent_id, m.c.person).where(
                m.c.tenant_id == current_tenant(), m.c.created_at < before, any_team(m, RETENTION)
            )
            rows = (await c.execute(q)).all()
            if not rows:
                return 0
            await c.execute(m.delete().where(m.c.id.in_([r.id for r in rows])))
            now = now_iso()
            await c.execute(
                memory_audit.insert(),
                [
                    {
                        "id": new_id("mau"),
                        "person": r.person,
                        "agent_id": r.agent_id,
                        "memory_id": r.id,
                        "action": "expire",
                        "actor": actor,
                        "at": now,
                    }
                    for r in rows
                ],
            )
        return len(rows)

    async def tenants(self) -> list[str]:
        """Every tenant holding a memory, read past row-level security: the retention loop starts before it knows a
        tenant and then works each one under its own (tests/store/test_tenancy.py holds the list of callers)."""
        async with system_tx(self.engine, RETENTION_TENANTS) as c:
            q = sa.select(agent_memories.c.tenant_id).where(any_team(agent_memories, RETENTION)).distinct()
            return list((await c.execute(q)).scalars())

    async def audit(self, person: str, action: str, *, actor: str, agent_id: str, memory_id: str | None = None) -> None:
        async with tenant_tx(self.engine) as c:
            await c.execute(
                memory_audit.insert().values(
                    id=new_id("mau"),
                    person=person,
                    agent_id=agent_id,
                    memory_id=memory_id,
                    action=action,
                    actor=actor,
                    at=now_iso(),
                )
            )

    async def audit_rows(self, person: str) -> list[dict[str, Any]]:
        a = memory_audit
        q = sa.select(a).where(a.c.tenant_id == current_tenant(), a.c.person == person).order_by(a.c.at.desc())
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]
