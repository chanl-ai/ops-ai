"""Watched folders: which places of a connection a team copies into Files, where the last check stopped, and what each
check found.

A watch holds a lease while a check runs, so two checks of one watch never run at once (Check now while a check runs
answers "already checking"). Only the lease holder saves the place and numbers events, so event numbers follow the
order the check wrote them. Events are kept 90 days and swept by the retention process."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

import sqlalchemy as sa
from pydantic import JsonValue

from ops_files.store.files import SYSTEM_ROLE, metadata
from ops_service_kit.http import Out
from ops_store import isolation
from ops_store.dialect import db_after, db_now, locked
from ops_store.schema import TENANT_SCOPED, team_owned
from ops_store.store import Store
from ops_store.team_scope import any_team, team_visible

from .files import ROLE

file_watches = sa.Table(
    "file_watches",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("plugin", sa.String(120), nullable=False),
    sa.Column("source", sa.String(120), nullable=False),
    sa.Column("connection_id", sa.String(64)),
    # The source's settings as the picker saved them (site, library, folders), sent to every call as `source`.
    sa.Column("values", sa.JSON, nullable=False),
    # ops_sources.Place, saved after every page by the lease holder.
    sa.Column("place", sa.JSON, nullable=False),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    # Set by Check now; the background process takes the watch and clears it when the check ends.
    sa.Column("check_requested_at", sa.DateTime(timezone=True)),
    sa.Column("lease_owner", sa.String(64)),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.Column("last_check_at", sa.DateTime(timezone=True)),
    # {status, brought, failed, stopped}: what the last check ended as, shown on the watch's row.
    sa.Column("last_outcome", sa.JSON),
    # The number the next event takes; moved only by the lease holder, in the transaction that writes the events.
    sa.Column("next_event", sa.Integer, nullable=False, server_default="1"),
    sa.Index("ix_file_watches_requested", "check_requested_at"),
    info={**TENANT_SCOPED, **team_owned("team")},
)

file_watch_events = sa.Table(
    "file_watch_events",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("watch_id", sa.String(64), primary_key=True),
    sa.Column("number", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("file_id", sa.String(64)),
    sa.Column("version", sa.Integer),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("reason", sa.String(500)),
    sa.Column("size", sa.BigInteger),
    sa.Column("path", sa.String(1024)),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_file_watch_events_at", "at"),
    info={**TENANT_SCOPED, **team_owned("team")},
)

EventKind = Literal["new", "changed", "renamed", "removed", "failed"]
# Why the retention process and the check process read past one tenant.
WATCHES_DUE = "background process: the watch check process lists each tenant's watches with a check asked for"
EVENTS_DUE = "background process: the retention process deletes each tenant's watch events past 90 days"


class NewWatch(TypedDict):
    tenant_id: str
    id: str
    team: str
    name: str
    plugin: str
    source: str
    connection_id: str | None
    values: dict[str, JsonValue]
    created_by: str
    created_at: datetime


class WatchEvent(TypedDict):
    file_id: str | None
    version: int | None
    kind: EventKind
    reason: str | None
    size: int | None
    path: str | None
    at: datetime


class WatchRow(Out):
    tenant_id: str
    id: str
    team: str
    name: str
    plugin: str
    source: str
    connection_id: str | None
    values: dict[str, JsonValue]
    place: dict[str, JsonValue]
    created_by: str
    created_at: datetime
    updated_at: datetime
    check_requested_at: datetime | None
    lease_owner: str | None
    lease_until: datetime | None
    last_check_at: datetime | None
    last_outcome: dict[str, JsonValue] | None
    next_event: int


class EventRow(Out):
    watch_id: str
    number: int
    file_id: str | None
    version: int | None
    kind: str
    reason: str | None
    size: int | None
    path: str | None
    at: datetime


class WatchesStore(Store):
    role = ROLE

    def _mine(self, watch_id: str) -> tuple[sa.ColumnElement[bool], ...]:
        w = file_watches
        return (w.c.tenant_id == isolation.tenant(), w.c.id == watch_id, team_visible(w))

    async def create(self, values: NewWatch) -> WatchRow:
        async with self.tx() as c:
            await c.execute(sa.insert(file_watches).values(**values, place={}, updated_at=values["created_at"]))
        found = await self.get(values["id"])
        assert found is not None
        return found

    async def get(self, watch_id: str) -> WatchRow | None:
        async with self.tx() as c:
            row = (await c.execute(sa.select(file_watches).where(*self._mine(watch_id)))).mappings().first()
        return WatchRow.model_validate(dict(row)) if row else None

    async def list(self, team: str) -> list[WatchRow]:
        w = file_watches
        q = sa.select(w).where(w.c.tenant_id == isolation.tenant(), w.c.team == team, team_visible(w))
        async with self.tx() as c:
            rows = (await c.execute(q.order_by(w.c.name, w.c.id))).mappings().all()
        return [WatchRow.model_validate(dict(r)) for r in rows]

    async def change(
        self, watch_id: str, *, name: str | None, values: dict[str, JsonValue] | None, at: datetime
    ) -> bool:
        """New folders start a fresh place, so the next check lists the new folders whole."""
        given: dict[str, object] = {"updated_at": at}
        if name is not None:
            given["name"] = name
        if values is not None:
            given["values"], given["place"] = values, {}
        async with self.tx() as c:
            return (await c.execute(sa.update(file_watches).where(*self._mine(watch_id)).values(**given))).rowcount == 1

    async def delete(self, watch_id: str) -> bool:
        e = file_watch_events
        async with self.tx() as c:
            await c.execute(sa.delete(e).where(e.c.tenant_id == isolation.tenant(), e.c.watch_id == watch_id))
            return (await c.execute(sa.delete(file_watches).where(*self._mine(watch_id)))).rowcount == 1

    async def request_check(self, watch_id: str, at: datetime) -> bool:
        """Asks for a check; false when one is already asked for or running, so two never run at once."""
        w = file_watches
        free = sa.and_(w.c.check_requested_at.is_(None), sa.or_(w.c.lease_until.is_(None), w.c.lease_until < db_now()))
        async with self.tx() as c:
            q = sa.update(w).where(*self._mine(watch_id), free).values(check_requested_at=at)
            return (await c.execute(q)).rowcount == 1

    async def asked(self, limit: int = 20) -> list[tuple[str, str, str]]:
        """(tenant, team, watch id) of every watch with a check asked for and no live lease, across tenants."""
        w = file_watches
        free = sa.or_(w.c.lease_until.is_(None), w.c.lease_until < db_now())
        q = (
            sa.select(w.c.tenant_id, w.c.team, w.c.id)
            .where(any_team(w, WATCHES_DUE), w.c.check_requested_at.is_not(None), free)
            .order_by(w.c.check_requested_at)
            .limit(limit)
        )
        async with isolation.system_tx(self.engine, WATCHES_DUE, role=SYSTEM_ROLE) as c:
            return [(str(r[0]), str(r[1]), str(r[2])) for r in await c.execute(q)]

    async def claim(self, watch_id: str, *, owner: str, seconds: float) -> bool:
        """Takes the watch's check lease for `owner` by the database's clock when nobody holds a live one."""
        w = file_watches
        free = sa.or_(w.c.lease_until.is_(None), w.c.lease_until < db_now())
        async with self.tx() as c:
            q = sa.update(w).where(*self._mine(watch_id), free).values(lease_owner=owner, lease_until=db_after(seconds))
            return (await c.execute(q)).rowcount == 1

    async def renew(self, watch_id: str, *, owner: str, seconds: float) -> bool:
        w = file_watches
        async with self.tx() as c:
            q = (
                sa.update(w)
                .where(*self._mine(watch_id), w.c.lease_owner == owner)
                .values(lease_until=db_after(seconds))
            )
            return (await c.execute(q)).rowcount == 1

    async def save_place(self, watch_id: str, *, owner: str, place: dict[str, JsonValue]) -> bool:
        """Keeps the place; false when `owner` lost the lease, so a check that ran over never overwrites a newer one."""
        w = file_watches
        async with self.tx() as c:
            q = sa.update(w).where(*self._mine(watch_id), w.c.lease_owner == owner).values(place=place)
            return (await c.execute(q)).rowcount == 1

    async def finish(self, watch_id: str, *, owner: str, outcome: dict[str, JsonValue], at: datetime) -> None:
        """Ends `owner`'s check: the outcome is kept on the watch, the request and the lease cleared."""
        w = file_watches
        async with self.tx() as c:
            await c.execute(
                sa.update(w)
                .where(*self._mine(watch_id), w.c.lease_owner == owner)
                .values(
                    last_outcome=outcome, last_check_at=at, check_requested_at=None, lease_owner=None, lease_until=None
                )
            )

    async def add_events(self, watch_id: str, *, owner: str, events: list[WatchEvent]) -> int:
        """Numbers and writes `events` as `owner`, in one transaction with the counter; 0 when it lost the lease."""
        if not events:
            return 0
        w, e = file_watches, file_watch_events
        async with self.tx() as c:
            q = locked(sa.select(w).where(*self._mine(watch_id), w.c.lease_owner == owner), w)
            held = (await c.execute(q)).mappings().first()
            if held is None:
                return 0
            start = int(held["next_event"])
            await c.execute(
                sa.insert(e),
                [
                    {
                        "tenant_id": isolation.tenant(),
                        "watch_id": watch_id,
                        "number": start + i,
                        "team": held["team"],
                        **ev,
                    }
                    for i, ev in enumerate(events)
                ],
            )
            await c.execute(sa.update(w).where(*self._mine(watch_id)).values(next_event=start + len(events)))
        return len(events)

    async def events(self, watch_id: str, *, after: int = 0, limit: int = 100) -> list[EventRow]:
        e = file_watch_events
        q = (
            sa.select(e)
            .where(e.c.tenant_id == isolation.tenant(), e.c.watch_id == watch_id, e.c.number > after, team_visible(e))
            .order_by(e.c.number)
            .limit(limit)
        )
        async with self.tx() as c:
            return [EventRow.model_validate(dict(r)) for r in (await c.execute(q)).mappings().all()]

    async def sweep_events(self, before: datetime) -> int:
        """Deletes every tenant's watch events older than `before`; the number deleted."""
        e = file_watch_events
        async with isolation.system_tx(self.engine, EVENTS_DUE, role=SYSTEM_ROLE) as c:
            return (await c.execute(sa.delete(e).where(any_team(e, EVENTS_DUE), e.c.at < before))).rowcount
