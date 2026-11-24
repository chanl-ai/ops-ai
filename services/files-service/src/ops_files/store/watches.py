"""Watched folders: which places of a connection a team copies into Files, where the last check stopped, and what each
check found.

A watch holds a lease while a check runs, so two checks of one watch never run at once (Check now while a check runs
answers "already checking"). Only the lease holder saves the place and numbers events, so event numbers follow the
order the check wrote them. Events are kept 90 days and swept by the retention process."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, NotRequired, TypedDict, cast

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_files.store.files import SYSTEM_ROLE, metadata, service_outbox
from ops_service_kit.http import ListPage, Out
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.audit import record as record_audit
from ops_store.dialect import db_after, db_now, locked
from ops_store.listing import list_page
from ops_store.outbox import add as add_event
from ops_store.schema import TENANT_SCOPED, team_owned
from ops_store.store import Store
from ops_store.team_scope import any_team, team_visible

from .files import ROLE, files

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
    # {input: {id: name}}: what the picker called each picked place, for the list; the calls are sent only `values`.
    sa.Column("value_names", sa.JSON),
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
    # {source id: "<size>:<version tag>"} of files refused for their size, so a check says one again only for a new
    # version.
    sa.Column("refused_sizes", sa.JSON),
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
    # Why a failed event failed: too_large (no retry brings it in) or fetch_failed; null for other kinds.
    sa.Column("code", sa.String(32)),
    sa.Column("size", sa.BigInteger),
    sa.Column("path", sa.String(1024)),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_file_watch_events_at", "at"),
    info={**TENANT_SCOPED, **team_owned("team")},
)

EventKind = Literal["new", "changed", "renamed", "removed", "failed"]
FailureCode = Literal["too_large", "fetch_failed"]
# The most refused files a watch remembers by size; past it a file is said again on its next listing.
REFUSED_KEPT = 500
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
    value_names: NotRequired[dict[str, dict[str, str]]]
    created_by: str
    created_at: datetime


class Audit(TypedDict):
    """A person's change to a watch, written to the account's audit log in the change's transaction."""

    actor: str
    action: str
    summary: str
    detail: dict[str, JsonValue]


# The service event a finished check reports, once per check (its key is the check's lease owner), so agents-service's
# Files changed trigger reads the new events after it.
CHECKED = "watch.checked"


class WatchEvent(TypedDict):
    file_id: str | None
    version: int | None
    kind: EventKind
    reason: str | None
    code: FailureCode | None
    size: int | None
    path: str | None
    at: datetime


def refused_since(before: dict[str, JsonValue] | None, outcome: dict[str, JsonValue], at: datetime) -> str | None:
    """While checks keep ending refused, when the first of the run ended; None once one is not refused. A trigger
    keys its one outage notice by it, so three refused checks are one outage."""
    if outcome.get("status") != "refused":
        return None
    kept = (before or {}).get("refusedSince") if (before or {}).get("status") == "refused" else None
    return kept if isinstance(kept, str) else at.isoformat()


class LeaseLost(Exception):
    """The check's lease passed to another check (it ran past its lease), so this one writes nothing more."""


async def write_events(c: AsyncConnection, watch_id: str, *, owner: str, events: list[WatchEvent]) -> None:
    """Numbers and writes `events` on `c` as `owner`, so a version and its event commit together; raises `LeaseLost`,
    rolling the transaction back, when `owner` no longer holds the watch's lease."""
    w, e = file_watches, file_watch_events
    tenant = isolation.tenant()
    mine = (w.c.tenant_id == tenant, w.c.id == watch_id, team_visible(w))
    held = (await c.execute(locked(sa.select(w).where(*mine, w.c.lease_owner == owner), w))).mappings().first()
    if held is None:
        raise LeaseLost(watch_id)
    if not events:
        return
    start = int(held["next_event"])
    rows = [
        {"tenant_id": tenant, "watch_id": watch_id, "number": start + i, "team": held["team"], **ev}
        for i, ev in enumerate(events)
    ]
    await c.execute(sa.insert(e), rows)
    await c.execute(sa.update(w).where(*mine).values(next_event=start + len(events)))


class WatchRow(Out):
    tenant_id: str
    id: str
    team: str
    name: str
    plugin: str
    source: str
    connection_id: str | None
    values: dict[str, JsonValue]
    value_names: dict[str, dict[str, str]] | None = None
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
    refused_sizes: dict[str, JsonValue] | None = None
    # The watch's files in Files now: its entries not removed at the source.
    files_in_files: int = 0


class EventRow(Out):
    tenant_id: str
    team: str
    watch_id: str
    number: int
    file_id: str | None
    version: int | None
    kind: str
    reason: str | None
    code: str | None = None
    size: int | None
    path: str | None
    at: datetime


class WatchesStore(Store):
    role = ROLE

    @staticmethod
    def _with_count() -> sa.Select[Any]:
        """The watch's row with how many of its files are in Files, counted in the same statement."""
        w, f = file_watches, files
        held = (
            sa.select(sa.func.count())
            .where(f.c.tenant_id == w.c.tenant_id, f.c.watch_id == w.c.id, f.c.removed_at.is_(None), team_visible(f))
            .correlate(w)
            .scalar_subquery()
        )
        return sa.select(w, held.label("files_in_files"))

    def _mine(self, watch_id: str) -> tuple[sa.ColumnElement[bool], ...]:
        w = file_watches
        return (w.c.tenant_id == isolation.tenant(), w.c.id == watch_id, team_visible(w))

    async def _audit(self, c: AsyncConnection, team: str, watch_id: str, audit: Audit) -> None:
        await record_audit(
            c,
            service_outbox,
            tenant_id=isolation.tenant(),
            team_id=team,
            actor=audit["actor"],
            action=audit["action"],
            target_kind="file_watch",
            target_id=watch_id,
            summary=audit["summary"],
            detail=audit["detail"],
        )

    async def create(self, values: NewWatch, *, audit: Audit) -> WatchRow:
        async with self.tx() as c:
            await c.execute(sa.insert(file_watches).values(**values, place={}, updated_at=values["created_at"]))
            await self._audit(c, values["team"], values["id"], audit)
        found = await self.get(values["id"])
        assert found is not None
        return found

    async def get(self, watch_id: str) -> WatchRow | None:
        async with self.tx() as c:
            row = (await c.execute(self._with_count().where(*self._mine(watch_id)))).mappings().first()
        return WatchRow.model_validate(dict(row)) if row else None

    async def list(self, team: str, params: ListParams) -> tuple[list[WatchRow], ListPage[dict[str, JsonValue]]]:
        """A page of the team's watches by name on the shared list contract, searched by name; the rows and the page
        they came from (its pagination)."""
        w = file_watches
        q = self._with_count().where(w.c.tenant_id == isolation.tenant(), w.c.team == team, team_visible(w))
        async with self.tx() as c:
            page = await list_page(c, q, params, search=(w.c.name,), default_sort=w.c.name.asc())
        return [WatchRow.model_validate(r) for r in page["data"]], page

    async def options(
        self, team: str, *, search: str, offset: int, limit: int, ids: list[str] | None
    ) -> list[tuple[str, str]]:
        """(id, name) of the team's watches a picker offers, searched and paged in the query; `ids` labels stored
        values instead."""
        w = file_watches
        q = sa.select(w.c.id, w.c.name).where(w.c.tenant_id == isolation.tenant(), w.c.team == team, team_visible(w))
        if ids is not None:
            q = q.where(w.c.id.in_(ids))
        elif search:
            q = q.where(sa.func.lower(w.c.name).contains(search.lower(), autoescape=True))
        q = q.order_by(w.c.name, w.c.id).offset(offset).limit(limit)
        async with self.tx() as c:
            return [(str(r[0]), str(r[1])) for r in await c.execute(q)]

    async def change(
        self,
        watch_id: str,
        *,
        name: str | None,
        values: dict[str, JsonValue] | None,
        names: dict[str, dict[str, str]] | None = None,
        at: datetime,
        audit: Audit,
    ) -> bool:
        """New folders start a fresh place, so the next check lists the new folders whole. `names` replaces the
        picked places' names when given; else the names kept still label the ids that remain."""
        given: dict[str, object] = {"updated_at": at}
        if name is not None:
            given["name"] = name
        if values is not None:
            given["values"], given["place"] = values, {}
        if names is not None:
            given["value_names"] = names
        async with self.tx() as c:
            team = (await c.execute(sa.select(file_watches.c.team).where(*self._mine(watch_id)))).scalar()
            if team is None:
                return False
            await c.execute(sa.update(file_watches).where(*self._mine(watch_id)).values(**given))
            await self._audit(c, str(team), watch_id, audit)
        return True

    async def delete(self, watch_id: str, *, audit: Audit) -> bool:
        """Deletes the watch and its events; false, deleting nothing, when the watch is not the caller's team's."""
        e = file_watch_events
        async with self.tx() as c:
            team = (await c.execute(sa.select(file_watches.c.team).where(*self._mine(watch_id)))).scalar()
            if team is None:
                return False
            await c.execute(sa.delete(e).where(e.c.tenant_id == isolation.tenant(), e.c.watch_id == watch_id))
            await c.execute(sa.delete(file_watches).where(*self._mine(watch_id)))
            await self._audit(c, str(team), watch_id, audit)
        return True

    async def request_check(self, watch_id: str, at: datetime, *, audit: Audit) -> bool:
        """Asks for a check; false when one is already asked for or running, so two never run at once. The audit
        entry is written only when the request was taken."""
        w = file_watches
        free = sa.and_(w.c.check_requested_at.is_(None), sa.or_(w.c.lease_until.is_(None), w.c.lease_until < db_now()))
        async with self.tx() as c:
            q = sa.update(w).where(*self._mine(watch_id), free).values(check_requested_at=at)
            if (await c.execute(q)).rowcount != 1:
                return False
            team = (await c.execute(sa.select(w.c.team).where(*self._mine(watch_id)))).scalar()
            await self._audit(c, str(team), watch_id, audit)
        return True

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

    async def save_place(self, watch_id: str, *, owner: str, place: dict[str, JsonValue], seconds: float) -> bool:
        """Keeps the place and renews the lease for `seconds`, so a long listing keeps its lease page by page; false
        when `owner` lost the lease, so a check that ran over never overwrites a newer one."""
        w = file_watches
        async with self.tx() as c:
            q = (
                sa.update(w)
                .where(*self._mine(watch_id), w.c.lease_owner == owner)
                .values(place=place, lease_until=db_after(seconds))
            )
            return (await c.execute(q)).rowcount == 1

    async def finish(self, watch_id: str, *, owner: str, outcome: dict[str, JsonValue], at: datetime) -> None:
        """Ends `owner`'s check: the outcome is kept on the watch, the request and the lease cleared, and the
        `watch.checked` event written in the same transaction, keyed by the check, so a relay reports each check
        once. A check that lost its lease writes neither."""
        w = file_watches
        async with self.tx() as c:
            before = (await c.execute(sa.select(w.c.last_outcome).where(*self._mine(watch_id)))).scalar()
            outcome = {**outcome, "refusedSince": refused_since(cast(dict[str, JsonValue] | None, before), outcome, at)}
            q = (
                sa.update(w)
                .where(*self._mine(watch_id), w.c.lease_owner == owner)
                .values(
                    last_outcome=outcome, last_check_at=at, check_requested_at=None, lease_owner=None, lease_until=None
                )
            )
            if (await c.execute(q)).rowcount != 1:
                return
            row = (await c.execute(sa.select(w.c.team, w.c.next_event).where(*self._mine(watch_id)))).one()
            await add_event(
                c,
                service_outbox,
                tenant_id=isolation.tenant(),
                team_id=str(row[0]),
                name=CHECKED,
                key=owner,
                payload={"watchId": watch_id, "lastEvent": int(row[1]) - 1, "checkedAt": at.isoformat(), **outcome},
            )

    async def refused_sizes(self, watch_id: str) -> dict[str, str]:
        """{source id: "<size>:<version tag>"} of the watch's files refused for their size, as the last check that saw
        them listed them."""
        async with self.tx() as c:
            found = (await c.execute(sa.select(file_watches.c.refused_sizes).where(*self._mine(watch_id)))).scalar()
        sizes = cast(dict[str, object], found or {})
        return {k: v for k, v in sizes.items() if isinstance(v, str)}

    async def save_refused_sizes(self, watch_id: str, *, owner: str, sizes: dict[str, str]) -> bool:
        """Keeps at most REFUSED_KEPT of `sizes` as `owner`; false when it no longer holds the lease."""
        kept = dict(list(sizes.items())[:REFUSED_KEPT])
        w = file_watches
        async with self.tx() as c:
            q = sa.update(w).where(*self._mine(watch_id), w.c.lease_owner == owner).values(refused_sizes=kept or None)
            return (await c.execute(q)).rowcount == 1

    async def add_events(self, watch_id: str, *, owner: str, events: list[WatchEvent]) -> int:
        """Numbers and writes `events` as `owner`, in one transaction with the counter; 0 when it lost the lease."""
        if not events:
            return 0
        try:
            async with self.tx() as c:
                await write_events(c, watch_id, owner=owner, events=events)
        except LeaseLost:
            return 0
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
