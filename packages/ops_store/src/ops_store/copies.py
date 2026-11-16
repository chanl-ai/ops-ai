"""A local copy of another service's records, kept by that service's events, so a screen lists and labels them in
one transaction instead of asking the owner inside the request.

  tools = copy_table(metadata, "tool_catalog", sa.Column("name", sa.String(200), nullable=False))  # with a migration
  await apply(conn, tools, event)      # in the route that receives the owner's event, as the event's tenant
  register(resync(tools, owner.list_all, key="tool_catalog_resync", service="agents", every_s=3600.0))
  await run_sweep("tool_catalog_resync", lambda: isolation.system_tx(engine, RESYNC, role=SYSTEM), stop=stop)

A copy row carries the owner's id and revision. The relay delivers at least once and in no promised order, so `apply`
writes an event only over an older revision: a replay or a late event changes nothing. The resync reads the owner's
full list and repairs what events missed. A copy answers what to show; a decision (may this caller run the tool) is
always asked of the owner.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from .background import Process
from .dialect import insert_ignore
from .schema import TEAM_KEY, TENANT_SCOPED

# The columns every copy has, beside the ones a screen lists or filters on.
OWN = ("tenant_id", "team_id", "id", "revision")


class Copied(Protocol):
    """One record as its owner reports it, in an event or in the owner's full list: `outbox.Event` is one. The payload
    names the record's `id` and its copied columns; `"deleted": true` says the record is gone."""

    @property
    def tenant_id(self) -> str: ...
    @property
    def team_id(self) -> str | None: ...
    @property
    def revision(self) -> int: ...
    @property
    def payload(self) -> Any: ...


Source = Callable[[], Awaitable[Sequence[Copied]]]


def copy_table(
    metadata: sa.MetaData, name: str, *columns: sa.Column[Any], marking: Mapping[str, Any] = TENANT_SCOPED
) -> sa.Table:
    """A local copy of another service's records: the owner's id, its revision, and the columns a screen lists or
    filters on. Policed like any tenant table. Never the source of truth for a decision.

    Keyed by tenant and id (and team, for a team-owned marking such as a team's state of a tool), so two tenants'
    records with one id are two rows, each behind its tenant's policy."""
    team = [sa.Column("team_id", sa.String(64), primary_key=True)] if isinstance(marking.get(TEAM_KEY), str) else []
    return sa.Table(
        name,
        metadata,
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        *team,
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("revision", sa.BigInteger, nullable=False),
        *columns,
        info=dict(marking),
    )


def _payload(record: Copied) -> dict[str, Any]:
    body = record.payload
    found: Mapping[str, Any] = body.model_dump() if isinstance(body, BaseModel) else body
    if not found.get("id"):
        raise ValueError(f"a copied record names its id in its payload; this one has {sorted(found)}")
    return dict(found)


def _keys(table: sa.Table, record: Copied, record_id: str) -> dict[str, Any]:
    keys: dict[str, Any] = {"tenant_id": record.tenant_id, "id": record_id}
    if "team_id" in table.c:
        keys["team_id"] = record.team_id
    return keys


def _row(table: sa.Table, record: Copied, body: Mapping[str, Any]) -> dict[str, Any]:
    """The copy's row for a record: its keys, its revision and the payload's values of the copied columns; a payload
    field the copy does not keep is left out."""
    values = {c: body[c] for c in (col.name for col in table.c) if c not in OWN and c in body}
    return {**_keys(table, record, str(body["id"])), "revision": record.revision, **values}


def _match(table: sa.Table, keys: Mapping[str, Any]) -> list[sa.ColumnElement[bool]]:
    return [table.c[k] == v for k, v in keys.items()]


async def apply(conn: AsyncConnection, table: sa.Table, event: Copied) -> None:
    """Upsert or delete by id and revision; an older revision is ignored, so a replayed event is harmless.

    Runs on the caller's transaction, as the event's tenant, so the copy's policy holds the write to that tenant. Two
    statements, each guarded in SQL rather than read first, so two deliveries at once cannot both win: an insert that
    does nothing when the row exists, then an update only over an older revision. A delete removes the row unless the
    copy already holds a newer revision; an older event re-delivered after a delete writes the row again, and the next
    resync removes it."""
    body = _payload(event)
    keys = _keys(table, event, str(body["id"]))
    if body.get("deleted"):
        await conn.execute(table.delete().where(*_match(table, keys), table.c.revision <= event.revision))
        return
    row = _row(table, event, body)
    await conn.execute(insert_ignore(conn, table, row, keys=list(keys)))
    changed = {c: v for c, v in row.items() if c not in keys}
    await conn.execute(table.update().where(*_match(table, keys), table.c.revision < event.revision).values(**changed))


async def reconcile(conn: AsyncConnection, table: sa.Table, records: Sequence[Copied]) -> int:
    """Makes the copy match the owner's full list: a row it lacks is written, a row older than the owner's is
    rewritten, and a row the owner no longer lists is deleted. Returns how many rows changed.

    The whole table is read once and the writes go in one statement per kind (and one delete per tenant), however
    many rows there are. A row newer than the list (an event applied after the owner answered) is kept."""
    key_cols = [c.name for c in table.primary_key.columns]
    held = {
        tuple(r[:-1]): int(r[-1])
        for r in await conn.execute(sa.select(*[table.c[k] for k in key_cols], table.c.revision))
    }
    wanted: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        body = _payload(record)
        if body.get("deleted"):
            continue
        row = _row(table, record, body)
        wanted[tuple(row[k] for k in key_cols)] = row
    missing = [row for key, row in wanted.items() if key not in held]
    stale = [row for key, row in wanted.items() if key in held and held[key] < row["revision"]]
    gone = [key for key in held if key not in wanted]
    if missing:
        await conn.execute(table.insert(), missing)
    for columns, rows in _by_columns(stale).items():
        changed = [c for c in columns if c not in key_cols]
        stmt = (
            table.update()
            .where(*[table.c[k] == sa.bindparam(f"k_{k}") for k in key_cols])
            .where(table.c.revision < sa.bindparam("k_revision"))
            .values({c: sa.bindparam(f"v_{c}") for c in changed})
        )
        await conn.execute(
            stmt,
            [
                {**{f"k_{k}": r[k] for k in key_cols}, "k_revision": r["revision"], **{f"v_{c}": r[c] for c in changed}}
                for r in rows
            ],
        )
    for tenant, keys in _by_tenant(gone, key_cols).items():
        rest = [k for k in key_cols if k != "tenant_id"]
        if len(rest) == 1:
            where = table.c[rest[0]].in_([k[0] for k in keys])
        else:
            where = sa.or_(*[sa.and_(*[table.c[c] == v for c, v in zip(rest, k, strict=True)]) for k in keys])
        await conn.execute(table.delete().where(table.c.tenant_id == tenant, where))
    return len(missing) + len(stale) + len(gone)


def _by_columns(rows: list[dict[str, Any]]) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    # One executemany needs one shape; rows whose owner left a column out are a second batch, not a null written.
    out: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(tuple(r), []).append(r)
    return out


def _by_tenant(keys: list[tuple[Any, ...]], key_cols: list[str]) -> dict[str, list[tuple[Any, ...]]]:
    at = key_cols.index("tenant_id")
    out: dict[str, list[tuple[Any, ...]]] = {}
    for k in keys:
        out.setdefault(str(k[at]), []).append(k[:at] + k[at + 1 :])
    return out


def resync(table: sa.Table, source: Source, *, key: str, every_s: float, service: str) -> Process:
    """Reads the owner's full list at start and every every_s and reconciles the copy.

    The process is listed once `background.register`ed and run by `background.run_sweep`, whose `tx` is the service's
    `system_tx` with its reason and system role, since the list is every tenant's. A pass whose source raises writes
    nothing and shows on /health/background; a service's tests hold it to `testing.loop_reports_failure`."""

    async def sweep(conn: AsyncConnection, _now: float) -> int:
        return await reconcile(conn, table, await source())

    return Process(
        key,
        service,
        f"Copy of {table.name}",
        f"Reads the owning service's full list and repairs rows of {table.name} that events missed.",
        every_s,
        "The owner's list is every tenant's; the copy is reconciled as the service's system role.",
        sweep=sweep,
    )
