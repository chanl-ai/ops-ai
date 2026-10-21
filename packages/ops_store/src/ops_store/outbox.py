"""The service event outbox (c-258): a service writes the event it reports in the same transaction as the change the
event is about, and a relay delivers it to agents-service's POST /v1/events afterwards. Neither is lost when the other
is down: the change and its event commit together, and the relay retries until delivery.

Delivery is at least once: a relay that stops after sending and before marking the row sent sends it again, and
agents-service returns the run the first delivery started, by the event's key.

  events = outbox_table(metadata)             # in the service's own store, with a migration
  await add(conn, events, tenant_id=..., team_id=..., name="file.deleted", key=file_id, payload={...})
  relay = Relay(engine, events, send)         # send POSTs one event, raising on any failure
  await relay.once()                          # or: await relay.run(stop), which also prunes
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from . import isolation
from .dialect import claim
from .schema import system

# An outbox not yet held to its tenant by the database (tools-service's, until c-414); a service that isolates its
# outbox passes TENANT_SCOPED: the request role then reads and writes its own tenant's events, and the relay reads
# every tenant's as the service's system role (c-415).
OUTBOX = system("service event outbox, read by its relay across tenants")
# Why the relay reads past the tenant: it delivers every tenant's due events.
RELAY = "outbox_relay"

Send = Callable[[dict[str, Any]], Awaitable[None]]

# The longest wait between two tries of one event, so a long outage is retried within a minute of its end.
MAX_BACKOFF_S = 60.0
# How long a delivered event is kept, and one never to be sent (replaced before it was due) after it was written: a
# week to answer whether an event went out, after which the table stops growing. The relay prunes once an hour.
KEEP_S = 7 * 86400.0
PRUNE_EVERY_S = 3600.0


def outbox_table(metadata: sa.MetaData, name: str = "service_outbox", *, info: dict[str, Any] = OUTBOX) -> sa.Table:
    """The outbox's columns. Read by the relay across tenants through `isolation.system_tx`; `info` is its
    isolation marking."""
    return sa.Table(
        name,
        metadata,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("event_key", sa.String(200), nullable=False),
        sa.Column("actor", sa.String(320)),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.Float(asdecimal=False), nullable=False),
        # Unix seconds when the relay may next try; null once sent.
        sa.Column("next_at", sa.Float(asdecimal=False)),
        sa.Column("sent_at", sa.Float(asdecimal=False)),
        sa.Column("attempts", sa.Integer, nullable=False, default=0),
        sa.Column("last_error", sa.Text),
        sa.Index(f"ix_{name}_due", "sent_at", "next_at"),
        info=info,
    )


async def add(
    conn: AsyncConnection,
    table: sa.Table,
    *,
    tenant_id: str,
    team_id: str,
    name: str,
    key: str,
    payload: dict[str, Any],
    actor: str | None = None,
    now: float | None = None,
    due_at: float | None = None,
) -> None:
    """Writes the event on the caller's connection, inside the transaction that makes the change it reports. `due_at`
    holds it back until then, so a later event about the same thing can replace it before it is sent."""
    at = time.time() if now is None else now
    await conn.execute(
        table.insert().values(
            id=f"obx_{uuid.uuid4().hex}",
            tenant_id=tenant_id,
            team_id=team_id,
            name=name,
            event_key=key,
            actor=actor,
            payload=payload,
            created_at=at,
            next_at=at if due_at is None else due_at,
            attempts=0,
        )
    )


def wire(row: dict[str, Any]) -> dict[str, Any]:
    """The POST /v1/events body for a row, with its tenant beside it for the token the send mints."""
    body: dict[str, Any] = {
        "name": row["name"],
        "key": row["event_key"],
        "teamId": row["team_id"],
        "payload": row["payload"],
    }
    if row["actor"]:
        body["actor"] = row["actor"]
    return {"tenantId": row["tenant_id"], "body": body}


class Relay:
    def __init__(
        self,
        engine: AsyncEngine,
        table: sa.Table,
        send: Send,
        *,
        role: str | None = None,
        batch: int = 20,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """`role` is the service's system role (BYPASSRLS, granted only its outbox) the relay reads and marks events
        as; None for an outbox with no policy."""
        self.engine, self.table, self.send, self.batch, self.clock = engine, table, send, batch, clock
        self.role = role

    async def once(self) -> int:
        """Tries every due event once, oldest first; returns how many were delivered. A failure is recorded and the
        event waits twice as long as before, up to a minute, so one bad event never holds the others back."""
        t = self.table
        now = self.clock()
        due = sa.select(t).where(t.c.sent_at.is_(None), t.c.next_at <= now).order_by(t.c.created_at).limit(self.batch)
        # Two relays never deliver the same batch at once; each takes the rows the other has not locked.
        due = claim(due, t)
        delivered = 0
        async with isolation.system_tx(self.engine, RELAY, role=self.role) as conn:
            rows = [dict(r) for r in (await conn.execute(due)).mappings()]
            for row in rows:
                try:
                    # What the send records about the event (a read request's run) is written as its tenant and team.
                    with isolation.scope(str(row["tenant_id"]), str(row["team_id"])):
                        await self.send(wire(row))
                except Exception as e:
                    tries = int(row["attempts"]) + 1
                    await conn.execute(
                        t.update()
                        .where(t.c.id == row["id"])
                        .values(
                            attempts=tries,
                            next_at=now + min(MAX_BACKOFF_S, 2.0**tries),
                            last_error=f"{type(e).__name__}: {e}"[:2000],
                        )
                    )
                    continue
                await conn.execute(
                    t.update()
                    .where(t.c.id == row["id"])
                    .values(sent_at=now, next_at=None, attempts=int(row["attempts"]) + 1, last_error=None)
                )
                delivered += 1
        return delivered

    async def prune(self, *, keep_s: float = KEEP_S) -> int:
        """Deletes events delivered more than `keep_s` ago and events never to be sent (no `sent_at` and no `next_at`)
        written that long ago; an event still being retried is kept however old. Returns how many were deleted."""
        t = self.table
        cutoff = self.clock() - keep_s
        never = sa.and_(t.c.sent_at.is_(None), t.c.next_at.is_(None), t.c.created_at < cutoff)
        async with isolation.system_tx(self.engine, RELAY, role=self.role) as conn:
            gone = await conn.execute(t.delete().where(sa.or_(t.c.sent_at < cutoff, never)))
        return int(gone.rowcount or 0)

    async def run(self, stop: asyncio.Event, *, every_s: float = 2.0) -> None:
        """Delivers until `stop` is set, waking every `every_s` seconds, and prunes once every PRUNE_EVERY_S."""
        pruned = float("-inf")
        while not stop.is_set():
            if self.clock() - pruned >= PRUNE_EVERY_S:
                await self.prune()
                pruned = self.clock()
            await self.once()
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=every_s)
