"""What agents remember about each person (c-124): keyed by person and team, never by conversation, so a memory
follows the person into their next chat in that team and no one else's. An empty agent_id means every agent in the
team (c-557); a set one keeps the memory to that agent. A replaced memory is kept as history with its status."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, ClassVar, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.dialect import insert_ignore, lock_key
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, full_text
from ops_store.team_scope import any_team, team_visible

from .base import metadata
from .tenancy import RETENTION_TENANTS, current_team, current_tenant, system_tx, tenant_tx

ACTIVE = "active"
SUGGESTED = "suggested"
CONFLICT = "conflict"
SUPERSEDED = "superseded"
FORGOTTEN = "forgotten"
STATUSES = (ACTIVE, SUGGESTED, CONFLICT, SUPERSEDED, FORGOTTEN)
# A memory the person can still forget or take back: in use, or waiting for their answer.
OPEN = (ACTIVE, SUGGESTED, CONFLICT)
# Where a memory came from: the person wrote it themselves (a correction), they asked for it ("remember that ..."),
# or it was learned from what they said.
PERSON = "person"
ASKED_FOR = "asked"
# How long a forgotten memory can be taken back before its text is erased.
FORGET_GRACE = timedelta(days=30)
# A memory's key and value as one full-text document on PostgreSQL. It is not indexed: every query first narrows to one
# person's memories by ix_agent_memories_owner, and ranking those few rows needs no full-text index.
# The `simple` dictionary does no stemming, so a word matches the same way as on SQL Server's neutral word breaker.
PG_DOCUMENT = "to_tsvector('simple', coalesce(key, '') || ' ' || value)"
_PG_DOCUMENT: sa.ColumnClause[Any] = sa.literal_column(PG_DOCUMENT)
# The words a full-text query is built from: letters and digits only, so no query syntax can come from a person.
_TOKEN = re.compile(r"[a-z0-9]+")
# The agent_id of a memory every agent in the team uses.
EVERY_AGENT = ""
IN_USE = "status = 'active' AND \"key\" IS NOT NULL"

agent_memories = sa.Table(
    "agent_memories",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, index=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    # Empty: every agent in the team; set: that agent only (rows saved before c-557 keep the agent they came from).
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
    # One of STATUSES; only active memories are recalled.
    sa.Column("status", sa.String(16), nullable=False, server_default=ACTIVE),
    # The person's own words the memory came from.
    sa.Column("quote", sa.String(500)),
    sa.Column("source_message_id", sa.String(64)),
    sa.Column("sensitivity", sa.String(16), nullable=False, server_default="none"),
    # The version this one replaced, so an undo can put it back and an erase can follow the chain.
    sa.Column("supersedes_id", sa.String(64)),
    sa.Column("confirmed_at", sa.String(32)),
    sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("last_used_at", sa.String(32)),
    # When a forgotten memory's text is erased.
    sa.Column("erase_after", sa.String(32)),
    sa.Index("ix_agent_memories_owner", "tenant_id", "person", "agent_id"),
    # One memory in use per key for a person and agent scope: two chats saving at once cannot both keep theirs.
    sa.Index(
        "ux_agent_memories_in_use",
        "tenant_id",
        "team_id",
        "person",
        "agent_id",
        "key",
        unique=True,
        postgresql_where=sa.text(IN_USE),
        sqlite_where=sa.text(IN_USE),
        mssql_where=sa.text(IN_USE),
    ),
    # Matched by full-text search on SQL Server where it is installed (migration 0085 on an upgraded install).
    info={**TENANT_SCOPED, **TEAM_OWNED, **full_text("ops_memory", "key", "value")},
)

memory_audit = sa.Table(
    "memory_audit",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, index=True),
    sa.Column("person", sa.String(320), nullable=False),
    # The team the memory belongs to; an export names the team it was asked from.
    sa.Column("team_id", sa.String(64), nullable=False, default=current_team),
    sa.Column("agent_id", sa.String(64), nullable=False),
    sa.Column("memory_id", sa.String(64)),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("actor", sa.String(320), nullable=False),
    sa.Column("at", sa.String(32), nullable=False),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


# The memories one answer used (c-557): ids only, so erasing a memory leaves nothing of its text here.
message_memory_use = sa.Table(
    "message_memory_use",
    metadata,
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("thread_id", sa.String(64), nullable=False),
    sa.Column("message_id", sa.String(64), nullable=False),
    sa.Column("memory_id", sa.String(64), nullable=False),
    # Why recall picked it: pinned (a standing preference or way of working) or matched (it fit the question).
    sa.Column("reason", sa.String(16), nullable=False),
    sa.Column("at", sa.String(32), nullable=False),
    sa.PrimaryKeyConstraint("tenant_id", "message_id", "memory_id", name="pk_message_memory_use"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


def erase_after(now: str) -> str:
    """FORGET_GRACE after `now`, written as now_iso writes times so the two compare as text."""
    later = datetime.fromisoformat(now) + FORGET_GRACE
    return later.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# Engines whose SQL Server has a full-text index on agent_memories, checked once each.
_FULL_TEXT: dict[str, bool] = {}


def _contains_literal(tokens: list[str]) -> str:
    """CONTAINSTABLE's search as an N'' literal, since it refuses the varchar(max) parameter the driver binds a string
    as. Only tokens of letters and digits reach it, so nothing in it can end the literal."""
    return "N'" + " OR ".join(f'"{w}"' for w in tokens if _TOKEN.fullmatch(w)) + "'"


async def _has_full_text_index(c: AsyncConnection) -> bool:
    """Whether this SQL Server indexes agent_memories for full-text: migration 0085 builds the index only where the
    server has Full-Text Search, so a server without it searches by counting words."""
    url = str(c.engine.url)
    if url not in _FULL_TEXT:
        q = sa.text("SELECT COUNT(*) FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID('agent_memories')")
        _FULL_TEXT[url] = bool((await c.execute(q)).scalar())
    return _FULL_TEXT[url]


def _get(row: Any, name: str) -> Any:
    """A column of a row read as a mapping or as a tuple."""
    if isinstance(row, dict):
        return cast(dict[str, Any], row)[name]
    return getattr(row, name)


def _audit(person: str, row: Any, action: str, actor: str, at: str) -> dict[str, Any]:
    """One memory_audit row for `action` on `row`: who, which team and which memory, never its text."""
    return {
        "id": new_id("mau"),
        "person": person,
        "team_id": _get(row, "team_id"),
        "agent_id": _get(row, "agent_id"),
        "memory_id": _get(row, "id"),
        "action": action,
        "actor": actor,
        "at": at,
    }


def _confirmed(row: dict[str, Any]) -> bool:
    """The person stands behind it: they said it again, asked for it (both stamp confirmed_at), or wrote it."""
    return bool(row.get("confirmed_at")) or row.get("source") == PERSON


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
        """The person's rows; with `agent_id`, that exact scope (EVERY_AGENT included)."""
        m = agent_memories.c
        where = [m.tenant_id == current_tenant(), m.person == person]
        return where if agent_id is None else [*where, m.agent_id == agent_id]

    def _for(self, person: str, agent_id: str | None) -> list[Any]:
        """What an agent may use: the person's memories kept to it and the ones every agent in the team uses."""
        m = agent_memories.c
        where = [m.tenant_id == current_tenant(), m.person == person]
        return where if agent_id is None else [*where, m.agent_id.in_([agent_id, EVERY_AGENT])]

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
        status: str = ACTIVE,
        quote: str | None = None,
        sensitivity: str = "none",
        supersedes_id: str | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Saves one memory. An active one replaces `supersedes_id` and the memory in use for its key in the same
        scope, unless that memory is one the person confirmed or wrote and this one is not confirmed: then both are
        kept, the new one in conflict, until the person chooses. A suggestion replaces nothing until the person says
        yes."""
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
            "status": status,
            "quote": quote,
            "sensitivity": sensitivity,
            "supersedes_id": supersedes_id,
            "confirmed_at": now if confirmed else None,
        }
        async with tenant_tx(self.engine) as c:
            # A thread's lease covers one thread, and the same person may chat in two at once: their saves in a team
            # take turns here, and the unique index refuses whatever would still leave two in use.
            await lock_key(c, f"memory:{current_tenant()}:{team_id}:{person}")
            if status == ACTIVE:
                same = [*self._mine(person, None), m.c.team_id == team_id, m.c.status == ACTIVE]
                hit = [m.c.id == supersedes_id] if supersedes_id else []
                if key:
                    hit.append(sa.and_(m.c.agent_id == agent_id, m.c.key == key))
                replaced = (
                    [dict(r) for r in (await c.execute(sa.select(m).where(*same, sa.or_(*hit)))).mappings()]
                    if hit
                    else []
                )
                held = next((r for r in replaced if _confirmed(r)), None)
                if held is not None and not confirmed:
                    row |= {"status": CONFLICT, "supersedes_id": held["id"]}
                elif replaced:
                    row["supersedes_id"] = supersedes_id or replaced[0]["id"]
                    await c.execute(
                        m.update()
                        .where(m.c.id.in_([r["id"] for r in replaced]))
                        .values(superseded_at=now, status=SUPERSEDED)
                    )
            await c.execute(m.insert().values(**row))
        return row

    async def confirm(self, person: str, team_id: str, memory_id: str) -> None:
        """The person said a memory again: it is confirmed, so a later learned contradiction asks before replacing."""
        m = agent_memories
        async with tenant_tx(self.engine) as c:
            await c.execute(
                m.update()
                .where(*self._mine(person, None), m.c.team_id == team_id, m.c.id == memory_id)
                .values(confirmed_at=now_iso())
            )

    async def undo(self, person: str, memory_id: str, *, actor: str) -> bool:
        """Takes back one of the person's memories: it is forgotten (erased after FORGET_GRACE), and when it had
        replaced another, that one is in use again. False when the person has no such memory in use or waiting."""
        m, now = agent_memories, now_iso()
        current = await self.get(person, memory_id)
        if current is None or current["status"] not in OPEN:
            return False
        async with tenant_tx(self.engine) as c:
            await lock_key(c, f"memory:{current_tenant()}:{current['team_id']}:{person}")
            await c.execute(
                m.update().where(m.c.id == memory_id).values(status=FORGOTTEN, erase_after=erase_after(now))
            )
            if current["status"] == ACTIVE and current["supersedes_id"]:
                await c.execute(
                    m.update()
                    .where(*self._mine(person, None), m.c.id == current["supersedes_id"], m.c.status == SUPERSEDED)
                    .values(status=ACTIVE, superseded_at=None)
                )
            await c.execute(memory_audit.insert().values(**_audit(person, current, "undo", actor, now)))
        return True

    async def by_ids(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Memories by id, whoever's, in the caller's tenant: what a thread's replies say they remembered."""
        if not ids:
            return {}
        m = agent_memories
        async with tenant_tx(self.engine) as c:
            q = sa.select(m).where(m.c.tenant_id == current_tenant(), team_visible(m), m.c.id.in_(ids))
            return {str(r["id"]): dict(r) for r in (await c.execute(q)).mappings()}

    async def current(
        self, person: str, agent_id: str | None = None, *, team_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """The person's memories in use, newest first; with `agent_id`, those that agent may use; with `team_id`,
        that team's only, named here because team_visible passes every team when the caller acts in none."""
        m = agent_memories
        q = sa.select(m).where(*self._for(person, agent_id), team_visible(m), m.c.status == ACTIVE)
        if team_id is not None:
            q = q.where(m.c.team_id == team_id)
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q.order_by(m.c.created_at.desc()).limit(limit))).mappings()]

    async def in_use(
        self, person: str, team_id: str, agent_id: str, *, kinds: tuple[str, ...] = (), limit: int = 200
    ) -> list[dict[str, Any]]:
        """The person's memories in use in this team that `agent_id` may use, of `kinds` when named, newest first. The
        team is named here, not left to team_visible, which passes every team when the caller acts in none."""
        m = agent_memories
        q = sa.select(m).where(
            *self._for(person, agent_id), m.c.team_id == team_id, team_visible(m), m.c.status == ACTIVE
        )
        if kinds:
            q = q.where(m.c.kind.in_(kinds))
        q = q.order_by(m.c.created_at.desc()).limit(limit)
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def record_use(self, team_id: str, thread_id: str, message_id: str, picks: list[tuple[str, str]]) -> None:
        """Records which memory versions one reply used and why, and counts each use once per reply (a resumed turn
        recalls again and records nothing new)."""
        u, m, now = message_memory_use, agent_memories, now_iso()
        async with tenant_tx(self.engine) as c:
            fresh: list[str] = []
            for memory_id, reason in picks:
                row = {
                    "tenant_id": current_tenant(),
                    "team_id": team_id,
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "memory_id": memory_id,
                    "reason": reason,
                    "at": now,
                }
                done = await c.execute(insert_ignore(c, u, row, keys=("tenant_id", "message_id", "memory_id")))
                if done.rowcount:
                    fresh.append(memory_id)
            if fresh:
                await c.execute(
                    m.update()
                    .where(m.c.tenant_id == current_tenant(), m.c.id.in_(fresh))
                    .values(use_count=m.c.use_count + 1, last_used_at=now)
                )

    async def matches(
        self, person: str, team_id: str, agent_id: str, words: list[str], *, limit: int = 10
    ) -> list[dict[str, Any]]:
        """The person's memories in use in this team that `agent_id` may use, best match for `words` first, each with
        its `match` score: found and ranked by the database across every such memory, however old. PostgreSQL ranks
        its full-text match, SQL Server its full-text index when the server has one; otherwise
        (SQLite, or SQL Server without Full-Text Search) the score is the number of words found, counted in SQL. The
        team is named here, not left to team_visible, which passes every team when the caller acts in none."""
        tokens = list(dict.fromkeys(w for word in words for w in _TOKEN.findall(word.lower())))
        if not tokens:
            return []
        m = agent_memories
        where = [*self._for(person, agent_id), m.c.team_id == team_id, team_visible(m), m.c.status == ACTIVE]
        async with tenant_tx(self.engine) as c:
            dialect = c.dialect.name
            if dialect == "postgresql":
                query = sa.func.to_tsquery(sa.literal_column("'simple'"), " | ".join(tokens))
                score: Any = sa.func.ts_rank(_PG_DOCUMENT, query)
                q = sa.select(m, score.label("match")).where(*where, _PG_DOCUMENT.op("@@")(query))
            elif dialect == "mssql" and await _has_full_text_index(c):
                found = (
                    sa.func.CONTAINSTABLE(
                        sa.literal_column("agent_memories"),
                        sa.literal_column("([key], value)"),
                        sa.literal_column(_contains_literal(tokens)),
                    )
                    .table_valued(sa.column("KEY"), sa.column("RANK"))
                    .alias("ft")
                )
                score = found.c.RANK
                q = sa.select(m, score.label("match")).join(found, m.c.id == found.c.KEY).where(*where)
            else:
                text = sa.func.lower(sa.func.coalesce(m.c.key, "") + " " + m.c.value)
                score = sum((sa.case((text.contains(w), 1), else_=0) for w in tokens), sa.literal(0))
                q = sa.select(m, score.label("match")).where(*where, score > 0)
            q = q.order_by(score.desc(), m.c.created_at.desc()).limit(limit)
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def supersede(self, person: str, memory_id: str) -> None:
        """Marks one of the person's memories replaced: a corrected episode, which has no key to supersede by."""
        m = agent_memories
        async with tenant_tx(self.engine) as c:
            await c.execute(
                m.update()
                .where(*self._mine(person, None), m.c.id == memory_id)
                .values(superseded_at=now_iso(), status=SUPERSEDED)
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
        """Forgets one of the person's memories in use or waiting, or all of those kept to one agent: each is left out
        at once and erased FORGET_GRACE later unless the person takes it back. Audited in the same transaction. The
        number forgotten."""
        m, now = agent_memories, now_iso()
        where = [*self._mine(person, None if memory_id else agent_id), m.c.status.in_(OPEN)]
        if memory_id:
            where.append(m.c.id == memory_id)
        async with tenant_tx(self.engine) as c:
            rows = (await c.execute(sa.select(m.c.id, m.c.agent_id, m.c.team_id).where(*where))).all()
            if not rows:
                return 0
            await c.execute(
                m.update()
                .where(m.c.id.in_([r.id for r in rows]))
                .values(status=FORGOTTEN, erase_after=erase_after(now))
            )
            await c.execute(memory_audit.insert(), [_audit(person, r, "forget", actor, now) for r in rows])
        return len(rows)

    async def restore(self, person: str, memory_id: str, *, actor: str) -> bool:
        """Takes back a forget within its grace: the memory is in use again, replacing whatever the person has in use
        for its key now. False when there is no such forgotten memory or its grace has passed."""
        m, now = agent_memories, now_iso()
        row = await self.get(person, memory_id)
        if row is None or row["status"] != FORGOTTEN or not row["erase_after"] or row["erase_after"] <= now:
            return False
        async with tenant_tx(self.engine) as c:
            await lock_key(c, f"memory:{current_tenant()}:{row['team_id']}:{person}")
            if row["key"]:
                await c.execute(
                    m.update()
                    .where(
                        *self._mine(person, str(row["agent_id"])),
                        m.c.team_id == row["team_id"],
                        m.c.key == row["key"],
                        m.c.status == ACTIVE,
                    )
                    .values(status=SUPERSEDED, superseded_at=now)
                )
            await c.execute(m.update().where(m.c.id == memory_id).values(status=ACTIVE, erase_after=None))
            await c.execute(memory_audit.insert().values(**_audit(person, row, "restore", actor, now)))
        return True

    async def erase(self, person: str, memory_id: str, *, actor: str) -> bool:
        """Erases one of the person's memories now, with every version it replaced. False when there is none."""
        row = await self.get(person, memory_id)
        if row is None:
            return False
        async with tenant_tx(self.engine) as c:
            await self._erase(c, [row], actor=actor)
        return True

    async def _erase(self, c: AsyncConnection, rows: list[Any], *, actor: str) -> Counter[str]:
        """Deletes `rows` and every version each replaced (its supersedes_id chain), auditing each by id only: the ids
        a reply or a use record holds then find no memory, which reads as forgotten. The memories asked for, per team
        (their earlier versions are not counted)."""
        m, now = agent_memories, now_iso()
        found = {str(_get(r, "id")): r for r in rows}
        frontier = [str(_get(r, "supersedes_id")) for r in rows if _get(r, "supersedes_id")]
        while frontier:
            older = (
                await c.execute(
                    sa.select(m.c.id, m.c.agent_id, m.c.team_id, m.c.person, m.c.supersedes_id).where(
                        m.c.tenant_id == current_tenant(), m.c.id.in_(frontier)
                    )
                )
            ).all()
            fresh = [r for r in older if str(r.id) not in found]
            found |= {str(r.id): r for r in fresh}
            frontier = [str(r.supersedes_id) for r in fresh if r.supersedes_id]
        await c.execute(m.delete().where(m.c.tenant_id == current_tenant(), m.c.id.in_(list(found))))
        await c.execute(
            memory_audit.insert(),
            [_audit(str(_get(r, "person")), r, "erase", actor, now) for r in found.values()],
        )
        return Counter(str(_get(r, "team_id")) for r in rows)

    async def expire(self, before: str, *, actor: str) -> Counter[str]:
        """Deletes the tenant's memories saved before `before` (every person and agent) and audits each as `expire` in
        the same transaction, for the workspace retention policy. The number deleted per team."""
        m = agent_memories
        async with tenant_tx(self.engine) as c:
            q = sa.select(m.c.id, m.c.agent_id, m.c.person, m.c.team_id).where(
                m.c.tenant_id == current_tenant(), m.c.created_at < before, any_team(m, RETENTION)
            )
            rows = (await c.execute(q)).all()
            if not rows:
                return Counter()
            await c.execute(m.delete().where(m.c.id.in_([r.id for r in rows])))
            now = now_iso()
            await c.execute(memory_audit.insert(), [_audit(r.person, r, "expire", actor, now) for r in rows])
        return Counter(str(r.team_id) for r in rows)

    async def erase_due(self, now: str, *, actor: str) -> Counter[str]:
        """Erases the tenant's forgotten memories whose grace ended by `now`, every person and team, each with the
        versions it replaced. The number erased per team."""
        return await self._erase_where(actor, agent_memories.c.status == FORGOTTEN, agent_memories.c.erase_after <= now)

    async def expire_suggestions(self, before: str, *, actor: str) -> Counter[str]:
        """Erases the tenant's suggestions saved before `before` that the person never answered, per team."""
        return await self._erase_where(
            actor, agent_memories.c.status == SUGGESTED, agent_memories.c.created_at < before
        )

    async def _erase_where(self, actor: str, *conditions: Any) -> Counter[str]:
        m = agent_memories
        async with tenant_tx(self.engine) as c:
            q = sa.select(m.c.id, m.c.agent_id, m.c.team_id, m.c.person, m.c.supersedes_id).where(
                m.c.tenant_id == current_tenant(), any_team(m, RETENTION), *conditions
            )
            rows = list((await c.execute(q)).all())
            return await self._erase(c, rows, actor=actor) if rows else Counter()

    async def tenants(self) -> list[str]:
        """Every tenant holding a memory, read past row-level security: the retention loop starts before it knows a
        tenant and then works each one under its own (tests/store/test_tenancy.py holds the list of callers)."""
        async with system_tx(self.engine, RETENTION_TENANTS) as c:
            q = sa.select(agent_memories.c.tenant_id).where(any_team(agent_memories, RETENTION)).distinct()
            return list((await c.execute(q)).scalars())

    async def audit(
        self,
        person: str,
        action: str,
        *,
        actor: str,
        agent_id: str,
        team_id: str,
        memory_id: str | None = None,
    ) -> None:
        async with tenant_tx(self.engine) as c:
            await c.execute(
                memory_audit.insert().values(
                    id=new_id("mau"),
                    person=person,
                    team_id=team_id,
                    agent_id=agent_id,
                    memory_id=memory_id,
                    action=action,
                    actor=actor,
                    at=now_iso(),
                )
            )

    async def audit_rows(self, person: str) -> list[dict[str, Any]]:
        a = memory_audit
        q = sa.select(a).where(a.c.tenant_id == current_tenant(), team_visible(a), a.c.person == person)
        q = q.order_by(a.c.at.desc())
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]
