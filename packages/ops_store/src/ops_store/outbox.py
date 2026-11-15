"""The service event outbox: a service writes the event it reports in the same transaction as the change the
event is about, and a relay delivers it to agents-service's POST /v1/events afterwards. Neither is lost when the other
is down: the change and its event commit together, and the relay retries until delivery.

Delivery is at least once: a relay that stops after sending and before marking the row sent sends it again, and
agents-service returns the run the first delivery started, by the event's key.

  events = outbox_table(metadata)             # in the service's own store, with a migration
  await add(conn, events, tenant_id=..., team_id=..., name="file.deleted", key=file_id, payload={...})
  r = relay(engine, events, routes={"*": ("agents",)}, targets={"agents": client}, role=SYSTEM_ROLE)
  await run_relay(r, key="files_relay", stop=stop)     # delivers, retries and prunes until stop

`relay()` is the one place a `Relay` is built (tests/test_relay_sites.py): a service passes which services hear each
event and the clients that reach them, and never writes its own send function or loop.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from . import background, isolation
from .dialect import claim
from .schema import system

# An outbox not yet held to its tenant by the database (tools-service's); a service that isolates its
# outbox passes TENANT_SCOPED: the request role then reads and writes its own tenant's events, and the relay reads
# every tenant's as the service's system role.
OUTBOX = system("service event outbox, read by its relay across tenants")
# Why the relay reads past the tenant: it delivers every tenant's due events.
RELAY = "outbox_relay"

Send = Callable[[dict[str, Any]], Awaitable[None]]


class Poster(Protocol):
    """What the relay needs of a client to another service; `ops_identity.ServiceClient` is one. `post` raises on
    any answer but success, and mints its token for the tenant and team it is given."""

    async def post(self, path: str, body: Any, /, *, tenant: str, team: str) -> Any: ...


# Event name -> the services that hear it. "*" is every event with no row of its own; an event with neither is
# delivered by doing nothing.
Routes = Mapping[str, tuple[str, ...]]
# Called after each delivery with the event's body, the service it went to and that service's answer, inside the
# event's tenant and team; raising leaves the event unsent.
Enrich = Callable[[dict[str, Any], str, Any], Awaitable[None]]

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

    async def waiting(self) -> int:
        """How many events are not yet sent and not given up on, for the relay's heartbeat."""
        t = self.table
        async with isolation.system_tx(self.engine, RELAY, role=self.role) as conn:
            count = await conn.scalar(
                sa.select(sa.func.count()).select_from(t).where(t.c.sent_at.is_(None), t.c.next_at.is_not(None))
            )
        return int(count or 0)

    async def run(
        self,
        stop: asyncio.Event,
        *,
        key: str,
        store: background.HeartbeatStore,
        every_s: float | None = None,
    ) -> None:
        """Delivers until `stop` is set, waking every `every_s` seconds (the listed interval of `key` by default), and
        prunes once every PRUNE_EVERY_S, as the listed background process `key`: a failed pass is retried with a
        growing wait and shows in its heartbeat."""
        pruned = float("-inf")

        async def once() -> int:
            nonlocal pruned
            if self.clock() - pruned >= PRUNE_EVERY_S:
                await self.prune()
                pruned = self.clock()
            return await self.once()

        await background.run(key, once, stop=stop, store=store, every_s=every_s, waiting=self.waiting)


def relay(
    engine: AsyncEngine,
    table: sa.Table,
    *,
    routes: Routes,
    targets: Mapping[str, Poster],
    role: str | None,
    path: str = "/v1/events",
    team_in_token: frozenset[str] = frozenset(),
    enrich: Enrich | None = None,
    path_by_target: Mapping[str, str] | None = None,
) -> Relay:
    """The relay of a service's outbox: each event is posted to every service `routes` names for it, at `path` (or
    that service's own in `path_by_target`), as the event's tenant and team.

    A service named in `routes` and absent from `targets` is one this installation does not run: nobody would read
    the event, so it is skipped. A delivery that raises leaves the event unsent and the relay sends it to all of its
    services again later, so a receiver dedupes on the event's key. A service in `team_in_token` takes the team from
    the token alone and its body carries no `teamId`."""
    paths = path_by_target or {}

    async def send(item: dict[str, Any]) -> None:
        body: dict[str, Any] = item["body"]
        tenant, team = str(item["tenantId"]), str(body["teamId"])
        for service in routes.get(str(body["name"]), routes.get("*", ())):
            if (poster := targets.get(service)) is None:
                continue
            sent = {k: v for k, v in body.items() if k != "teamId"} if service in team_in_token else body
            answer = await poster.post(paths.get(service, path), sent, tenant=tenant, team=team)
            if enrich is not None:
                await enrich(body, service, answer)

    return Relay(engine, table, send, role=role)


async def run_relay(
    r: Relay, *, key: str, stop: asyncio.Event, store: background.HeartbeatStore = background.LOCAL
) -> None:
    """Delivers and prunes until `stop` is set, as the listed background process `key`, at that process's listed
    interval; a failed pass is retried and shows on /health/background."""
    await r.run(stop, key=key, store=store)
