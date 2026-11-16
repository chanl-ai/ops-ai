"""A local copy of another service's records, kept by that service's events, so a screen lists and labels them in
one transaction instead of asking the owner inside the request.

  tools = copy_table(metadata, "tool_catalog", sa.Column("name", sa.String(200), nullable=False))  # with a migration
  await apply(conn, tools, event)      # in the route that receives the owner's event, as the event's tenant
  register(resync(tools, owner.list_all, key="tool_catalog_resync", service="agents", every_s=3600.0))
  await run_sweep("tool_catalog_resync", lambda: isolation.system_tx(engine, RESYNC, role=SYSTEM), stop=stop)

A copy row carries the owner's id and revision. The relay delivers at least once and in no promised order, so `apply`
writes an event only over an older revision: a replay or a late event changes nothing. A delete leaves a tombstone
(`tombstones(table)`, created beside the copy) holding the deleted revision, so an older event arriving after it
writes nothing. The resync reads the owner's full list, with no transaction open, and repairs what events missed. A
copy answers what to show; a decision (may this caller run the tool) is always asked of the owner.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from .background import Process, Tx
from .dialect import db_epoch, insert_ignore
from .outbox import KEEP_S, Event
from .schema import TEAM_KEY, TENANT_SCOPED

# The columns every copy has, beside the ones a screen lists or filters on.
OWN = ("tenant_id", "team_id", "id", "revision")
# How long a tombstone is kept once the owner no longer lists its record: the week the outbox keeps a sent event. An
# event the relay is still retrying after that (it retries without limit) can write the row back until the next resync.
TOMBSTONE_KEEP_S = KEEP_S

# The owner's full list: one `Event` per record it holds now, each with its current revision.
Source = Callable[[], Awaitable[Sequence[Event]]]
Key = tuple[Any, ...]


def copy_table(
    metadata: sa.MetaData, name: str, *columns: sa.Column[Any], marking: Mapping[str, Any] = TENANT_SCOPED
) -> sa.Table:
    """A local copy of another service's records: the owner's id, its revision, and the columns a screen lists or
    filters on. Policed like any tenant table. Never the source of truth for a decision.

    Keyed by tenant and id (and team, for a team-owned marking such as a team's state of a tool), so two tenants'
    records with one id are two rows, each behind its tenant's policy. Also adds `<name>_deleted` to `metadata`, the
    copy's tombstones (`tombstones`), with the same keys and marking; a migration creates both."""
    team = isinstance(marking.get(TEAM_KEY), str)

    def keys() -> list[sa.Column[Any]]:
        return [
            sa.Column("tenant_id", sa.String(64), primary_key=True),
            *([sa.Column("team_id", sa.String(64), primary_key=True)] if team else []),
            sa.Column("id", sa.String(200), primary_key=True),
            sa.Column("revision", sa.BigInteger, nullable=False),
        ]

    sa.Table(
        f"{name}_deleted",
        metadata,
        *keys(),
        # Seconds since 1970 on the database's clock when the delete was applied; the resync prunes by it.
        sa.Column("deleted_at", sa.Float(asdecimal=False), nullable=False),
        info=dict(marking),
    )
    return sa.Table(name, metadata, *keys(), *columns, info=dict(marking))


def tombstones(table: sa.Table) -> sa.Table:
    """The copy's tombstones: one row per deleted record, with the revision of its delete."""
    return table.metadata.tables[f"{table.key}_deleted"]


def _payload(record: Event) -> dict[str, Any]:
    found = record.payload.model_dump()
    if not found.get("id"):
        raise ValueError(f"{record.name}: a copied record names its id in its payload; this one has {sorted(found)}")
    return found


def _keys(table: sa.Table, record: Event, record_id: str) -> dict[str, Any]:
    keys: dict[str, Any] = {"tenant_id": record.tenant_id, "id": record_id}
    if "team_id" in table.c:
        keys["team_id"] = record.team_id
    return keys


def _row(table: sa.Table, record: Event, body: Mapping[str, Any]) -> dict[str, Any]:
    """The copy's row for a record: its keys, its revision and the payload's values of the copied columns; a payload
    field the copy does not keep is left out."""
    values = {c: body[c] for c in (col.name for col in table.c) if c not in OWN and c in body}
    return {**_keys(table, record, str(body["id"])), "revision": record.revision, **values}


def _match(table: sa.Table, keys: Mapping[str, Any]) -> list[sa.ColumnElement[bool]]:
    return [table.c[k] == v for k, v in keys.items()]


async def apply(conn: AsyncConnection, table: sa.Table, event: Event) -> None:
    """Upsert or delete by id and revision; an older revision is ignored, so a replayed event is harmless.

    Runs on the caller's transaction, as the event's tenant, so the copy's policy holds the write to that tenant. Each
    statement is guarded in SQL rather than read first, so two deliveries at once cannot both win: an insert that does
    nothing when the row exists, then an update only over an older revision. A delete removes the row unless the copy
    holds a newer revision and records its revision as a tombstone, even for a record the copy never held (a delete
    can arrive before its create); a later event no newer than the tombstone is removed again in the same transaction,
    and a newer one (the record is back) drops the tombstone."""
    body = _payload(event)
    keys = _keys(table, event, str(body["id"]))
    graves = tombstones(table)
    if body.get("deleted"):
        await conn.execute(table.delete().where(*_match(table, keys), table.c.revision <= event.revision))
        buried = {**keys, "revision": event.revision, "deleted_at": db_epoch()}
        await conn.execute(insert_ignore(conn, graves, buried, keys=list(keys)))
        await conn.execute(
            graves.update()
            .where(*_match(graves, keys), graves.c.revision < event.revision)
            .values(revision=event.revision, deleted_at=db_epoch())
        )
        return
    row = _row(table, event, body)
    await conn.execute(insert_ignore(conn, table, row, keys=list(keys)))
    changed = {c: v for c, v in row.items() if c not in keys}
    await conn.execute(table.update().where(*_match(table, keys), table.c.revision < event.revision).values(**changed))
    deleted_at = sa.select(graves.c.revision).where(*_match(graves, keys)).scalar_subquery()
    await conn.execute(table.delete().where(*_match(table, keys), table.c.revision <= deleted_at))
    await conn.execute(graves.delete().where(*_match(graves, keys), graves.c.revision < event.revision))


async def held(conn: AsyncConnection, table: sa.Table) -> dict[Key, int]:
    """Every row of the copy, by key, with its revision: what a resync pass compares the owner's list against."""
    key_cols = [c.name for c in table.primary_key.columns]
    found = await conn.execute(sa.select(*[table.c[k] for k in key_cols], table.c.revision))
    return {tuple(r[:-1]): int(r[-1]) for r in found}


async def reconcile(
    conn: AsyncConnection, table: sa.Table, records: Sequence[Event], before: Mapping[Key, int] | None = None
) -> int:
    """Makes the copy match the owner's full list: a row it lacks is written, a row older than the owner's is
    rewritten, and a row the owner no longer lists is deleted and tombstoned. Returns how many copy rows changed.

    `before` is the copy as read before the owner was asked (`held`). Only a row in it, at no newer revision, is deleted
    as unlisted: a row an event wrote while the owner answered is newer than the list and is kept. Without `before` the
    copy as read now is used. A record whose tombstone is at or past the listed revision is not written back (the list
    predates its delete). A tombstone is pruned once TOMBSTONE_KEEP_S old and its record unlisted, or at once when the
    owner lists the record at a newer revision. Every write is one statement per kind, however many rows."""
    key_cols = [c.name for c in table.primary_key.columns]
    graves = tombstones(table)
    now_held = await held(conn, table)
    age = db_epoch() - graves.c.deleted_at
    found = await conn.execute(sa.select(*[graves.c[k] for k in key_cols], graves.c.revision, age.label("age")))
    buried: dict[Key, tuple[int, float]] = {}
    for r in found:
        values = tuple(r)
        buried[values[:-2]] = (int(values[-2]), float(values[-1]))
    wanted: dict[Key, dict[str, Any]] = {}
    for record in records:
        body = _payload(record)
        if body.get("deleted"):
            continue
        row = _row(table, record, body)
        key = tuple(row[k] for k in key_cols)
        if key not in buried or buried[key][0] < row["revision"]:
            wanted[key] = row
    listed = {tuple(_row(table, r, _payload(r))[k] for k in key_cols) for r in records}
    missing = [row for key, row in wanted.items() if key not in now_held]
    stale = [row for key, row in wanted.items() if key in now_held and now_held[key] < row["revision"]]
    snapshot = now_held if before is None else before
    gone = {key: rev for key, rev in snapshot.items() if key not in listed and now_held.get(key) == rev}
    pruned = [
        (key, rev)
        for key, (rev, old) in buried.items()
        if (key not in listed and old > TOMBSTONE_KEEP_S) or key in wanted
    ]
    if missing:
        await conn.execute(table.insert(), missing)
    if stale:
        # Every row has one shape: a typed payload dumps each of its fields, so one executemany takes them all.
        changed = [c for c in stale[0] if c not in key_cols]
        await conn.execute(
            table.update()
            .where(*_by_key(table, key_cols), table.c.revision < sa.bindparam("k_revision"))
            .values({c: sa.bindparam(f"v_{c}") for c in changed}),
            [
                {**_key_params(key_cols, r), "k_revision": r["revision"], **{f"v_{c}": r[c] for c in changed}}
                for r in stale
            ],
        )
    if gone:
        await conn.execute(
            table.delete().where(*_by_key(table, key_cols), table.c.revision <= sa.bindparam("k_revision")),
            [{**_key_params(key_cols, dict(zip(key_cols, k, strict=True))), "k_revision": r} for k, r in gone.items()],
        )
        await _bury(conn, graves, key_cols, gone, {k: rev for k, (rev, _) in buried.items()})
    if pruned:
        await conn.execute(
            graves.delete().where(*_by_key(graves, key_cols), graves.c.revision == sa.bindparam("k_revision")),
            [{**_key_params(key_cols, dict(zip(key_cols, k, strict=True))), "k_revision": r} for k, r in pruned],
        )
    return len(missing) + len(stale) + len(gone)


async def _bury(
    conn: AsyncConnection, graves: sa.Table, key_cols: list[str], dead: Mapping[Key, int], have: Mapping[Key, int]
) -> None:
    """Tombstones for rows the resync deleted, so an event they already had does not write them back."""
    new = [{**dict(zip(key_cols, k, strict=True)), "revision": r} for k, r in dead.items() if k not in have]
    raised = [(k, r) for k, r in dead.items() if k in have and have[k] < r]
    if new:
        await conn.execute(graves.insert().values(deleted_at=db_epoch()), new)
    if raised:
        await conn.execute(
            graves.update()
            .where(*_by_key(graves, key_cols), graves.c.revision < sa.bindparam("k_revision"))
            .values(revision=sa.bindparam("v_revision"), deleted_at=db_epoch()),
            [
                {**_key_params(key_cols, dict(zip(key_cols, k, strict=True))), "k_revision": r, "v_revision": r}
                for k, r in raised
            ],
        )


def _by_key(table: sa.Table, key_cols: list[str]) -> list[sa.ColumnElement[bool]]:
    return [table.c[k] == sa.bindparam(f"k_{k}") for k in key_cols]


def _key_params(key_cols: list[str], row: Mapping[str, Any]) -> dict[str, Any]:
    return {f"k_{k}": row[k] for k in key_cols}


def resync(table: sa.Table, source: Source, *, key: str, every_s: float, service: str) -> Process:
    """Reads the owner's full list at start and every every_s and reconciles the copy.

    The process is listed once `background.register`ed and run by `background.run_sweep`, whose `tx` is the service's
    `system_tx` with its reason and system role, since the list is every tenant's. A pass reads the copy in one
    transaction, closes it, asks the owner with no transaction open, then reconciles in a second transaction, so no
    connection is held across the call. A pass whose source raises writes nothing and shows on /health/background; a
    service's tests hold it to `testing.loop_reports_failure`."""

    async def cycle(tx: Tx, _now: float) -> int:
        async with tx() as conn:
            before = await held(conn, table)
        records = await source()
        async with tx() as conn:
            return await reconcile(conn, table, records, before)

    return Process(
        key,
        service,
        f"Copy of {table.name}",
        f"Reads the owning service's full list and repairs rows of {table.name} that events missed.",
        every_s,
        "The owner's list is every tenant's; the copy is reconciled as the service's system role.",
        cycle=cycle,
    )
