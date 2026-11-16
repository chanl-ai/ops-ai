"""A local copy of another service's records, kept by that service's events, so a screen lists and labels them in
one transaction instead of asking the owner inside the request.

  tools = copy_table(metadata, "tool_catalog", sa.Column("name", sa.String(200), nullable=False))  # with a migration
  await apply(conn, tools, event)      # in the route that receives the owner's event, as the event's tenant
  sa.select(tools).where(live(tools))  # every read for a screen: a deleted record keeps its row as a tombstone
  register(resync(tools, owner.list_all, key="tool_catalog_resync", service="agents", every_s=3600.0))
  await run_sweep("tool_catalog_resync", lambda: isolation.system_tx(engine, RESYNC, role=SYSTEM), stop=stop)

A copy row carries the owner's id, its revision and a deleted flag. A delete keeps the row, flagged, as the record's
tombstone, so an event and a delete for one key always meet on one row and serialise on its lock. The revision
contract:

- Events are ordered by (revision, deleted), a delete after a write at the same revision. The relay delivers at least
  once and in no promised order, so `apply` writes an event only over a lower pair: a replay, a late event, or a write
  at the revision of its delete changes nothing. An owner whose revision does not rise (an edit at the same revision, a
  re-create below its delete, a counter that restarts, a clock that steps back) is not followed by events alone.
- The resync makes the copy equal to the owner's full list whatever the revisions, since the list is the truth: a row
  is set to what the owner lists unless an event changed it while the owner answered, and that row waits for the next
  pass. With no event in flight, one pass leaves the live rows equal to the list.

A delete event carries the same payload model as a write, so the tombstone of a record the copy never held (a delete
can arrive before its create) fills the copy's columns from it. A copy answers what to show; a decision (may this
caller run the tool) is always asked of the owner.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from .background import Process, Tx
from .dialect import db_epoch, insert_ignore
from .outbox import KEEP_S, Event
from .schema import TEAM_KEY, TENANT_SCOPED

# The columns every copy has, beside the ones a screen lists or filters on.
OWN = ("tenant_id", "team_id", "id", "revision", "deleted", "deleted_at")
# How long a tombstone is kept once the owner no longer lists its record: the week the outbox keeps a sent event. An
# event the relay is still retrying after that (it retries without limit) can write the row back until the next resync.
TOMBSTONE_KEEP_S = KEEP_S

# The owner's full list: one `Event` per record it holds now, each with its current revision.
Source = Callable[[], Awaitable[Sequence[Event]]]
Key = tuple[Any, ...]


def copy_table(
    metadata: sa.MetaData, name: str, *columns: sa.Column[Any], marking: Mapping[str, Any] = TENANT_SCOPED
) -> sa.Table:
    """A local copy of another service's records: the owner's id, its revision, whether it is deleted, and the columns
    a screen lists or filters on. Policed like any tenant table. Never the source of truth for a decision.

    Keyed by tenant and id (and team, for a team-owned marking such as a team's state of a tool), so two tenants'
    records with one id are two rows, each behind its tenant's policy. A deleted record's row stays as its tombstone
    until the resync prunes it; a read for a screen carries `live(table)`."""
    taken = [c.name for c in columns if c.name in OWN]
    if taken:
        raise ValueError(f"{name}: {taken} are the copy's own columns; name the copied field differently")
    team = isinstance(marking.get(TEAM_KEY), str)
    return sa.Table(
        name,
        metadata,
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        *([sa.Column("team_id", sa.String(64), primary_key=True)] if team else []),
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("revision", sa.BigInteger, nullable=False),
        sa.Column("deleted", sa.Boolean, nullable=False, default=False),
        # Seconds since 1970 on the database's clock when the row became a tombstone; the resync prunes by it.
        sa.Column("deleted_at", sa.Float(asdecimal=False), nullable=True),
        *columns,
        info=dict(marking),
    )


def live(table: sa.Table) -> sa.ColumnElement[bool]:
    """The where-clause of every read of a copy for a screen: the records the owner holds, without tombstones."""
    return table.c.deleted == sa.false()


@dataclass(frozen=True)
class Held:
    """A copy row as a resync pass read it, before asking the owner: the state a write is guarded on."""

    revision: int
    deleted: bool
    values: tuple[Any, ...]  # the copied columns, in the table's order
    age: float | None  # seconds since the row became a tombstone


def _key_cols(table: sa.Table) -> list[str]:
    return [c.name for c in table.primary_key.columns]


def _copied(table: sa.Table) -> list[str]:
    return [c.name for c in table.c if c.name not in OWN]


def _payload(record: Event) -> dict[str, Any]:
    found = record.payload.model_dump()
    if not found.get("id"):
        raise ValueError(f"{record.name}: a copied record names its id in its payload; this one has {sorted(found)}")
    return found


def _keys(table: sa.Table, record: Event, record_id: str) -> dict[str, str | None]:
    team = {"team_id": record.team_id} if "team_id" in table.c else {}
    return {"tenant_id": record.tenant_id, **team, "id": record_id}


def _row(table: sa.Table, record: Event, body: Mapping[str, Any]) -> dict[str, Any]:
    """The copy's row for a record: its keys, revision, deleted flag and the payload's values of the copied columns;
    a payload field the copy does not keep is left out."""
    values = {c: body[c] for c in _copied(table) if c in body}
    keys = _keys(table, record, str(body["id"]))
    return {**keys, "revision": record.revision, "deleted": bool(body.get("deleted")), "deleted_at": None, **values}


def _match(table: sa.Table, keys: Mapping[str, Any]) -> list[sa.ColumnElement[bool]]:
    return [table.c[k] == v for k, v in keys.items()]


async def apply(conn: AsyncConnection, table: sa.Table, event: Event) -> None:
    """Upsert, or mark deleted, by id and (revision, deleted); a lower pair is ignored, so a replayed event is
    harmless.

    Runs on the caller's transaction, as the event's tenant, so the copy's policy holds the write to that tenant. Both
    statements are guarded in SQL rather than read first, so two deliveries at once cannot both win: an insert that
    does nothing when the row exists, which makes a second writer of the key wait on the first, then an update only
    over a lower pair. A delete of a record the copy never held inserts its tombstone."""
    body = _payload(event)
    keys = _keys(table, event, str(body["id"]))
    row = _row(table, event, body)
    lower = table.c.revision < event.revision
    if row["deleted"]:
        row["deleted_at"] = db_epoch()
        lower = sa.or_(lower, sa.and_(table.c.revision == event.revision, live(table)))
        changed = {c: row[c] for c in ("revision", "deleted", "deleted_at")}
    else:
        changed = {c: v for c, v in row.items() if c not in keys}
    await conn.execute(insert_ignore(conn, table, row, keys=list(keys)))
    await conn.execute(table.update().where(*_match(table, keys), lower).values(**changed))


async def held(conn: AsyncConnection, table: sa.Table) -> dict[Key, Held]:
    """Every row of the copy, tombstones included, by key: what a resync pass compares the owner's list against."""
    key_cols, copied = _key_cols(table), _copied(table)
    age = (db_epoch() - table.c.deleted_at).label("tombstone_age")
    found = await conn.execute(
        sa.select(
            *[table.c[k] for k in key_cols], table.c.revision, table.c.deleted, age, *[table.c[c] for c in copied]
        )
    )
    n = len(key_cols)
    rows: dict[Key, Held] = {}
    for r in found:
        v = tuple(r)
        rows[v[:n]] = Held(int(v[n]), bool(v[n + 1]), v[n + 3 :], None if v[n + 2] is None else float(v[n + 2]))
    return rows


async def reconcile(
    conn: AsyncConnection, table: sa.Table, records: Sequence[Event], before: Mapping[Key, Held] | None = None
) -> int:
    """Makes the copy equal to the owner's full list: a row it lacks is written, a row that differs from the owner's
    record in revision, content or deleted flag is set to it, and a live row the owner no longer lists becomes a
    tombstone. Returns how many copy rows changed.

    `before` is the copy as read before the owner was asked (`held`); without it the copy as read now is used. Every
    write of a row in it is guarded on the revision and deleted flag read then, so a row an event changed while the
    owner answered is kept; a row it lacked is inserted unless an event wrote it meanwhile. A tombstone is pruned once
    TOMBSTONE_KEEP_S old and its record unlisted. Every write is one statement per kind, however many rows."""
    key_cols, copied = _key_cols(table), _copied(table)
    seen = await held(conn, table) if before is None else before
    wanted: dict[Key, dict[str, Any]] = {}
    for record in records:
        body = _payload(record)
        if not body.get("deleted"):
            row = _row(table, record, body)
            wanted[tuple(row[k] for k in key_cols)] = row
    missing = [row for key, row in _ordered(wanted) if key not in seen]
    differs = [
        (key, seen[key], row)
        for key, row in _ordered(wanted)
        if key in seen
        and (seen[key].revision, seen[key].deleted, seen[key].values)
        != (row["revision"], False, tuple(row.get(c) for c in copied))
    ]
    unlisted = [(key, h) for key, h in _ordered(seen) if key not in wanted]
    buried = [(key, h) for key, h in unlisted if not h.deleted]
    pruned = [(key, h) for key, h in unlisted if h.deleted and (h.age or 0.0) > TOMBSTONE_KEEP_S]
    if missing:
        # Every row has one shape: a typed payload dumps each of its fields, so one statement takes them all.
        cols = list(missing[0])
        params = {c: sa.bindparam(f"v_{c}", type_=table.c[c].type) for c in cols}
        await conn.execute(
            insert_ignore(conn, table, params, keys=key_cols), [{f"v_{c}": r[c] for c in cols} for r in missing]
        )
    if differs:
        changed = [c for c in differs[0][2] if c not in key_cols and c not in ("deleted", "deleted_at")]
        await conn.execute(
            table.update()
            .where(*_unchanged(table, key_cols))
            .values({**{c: sa.bindparam(f"v_{c}") for c in changed}, "deleted": sa.false(), "deleted_at": sa.null()}),
            [{**_was(key_cols, k, h), **{f"v_{c}": r[c] for c in changed}} for k, h, r in differs],
        )
    if buried:
        await conn.execute(
            table.update().where(*_unchanged(table, key_cols)).values(deleted=sa.true(), deleted_at=db_epoch()),
            [_was(key_cols, k, h) for k, h in buried],
        )
    if pruned:
        unchanged = [_was(key_cols, k, h) for k, h in pruned]
        await conn.execute(table.delete().where(*_unchanged(table, key_cols)), unchanged)
    return len(missing) + len(differs) + len(buried)


def _ordered[V](rows: Mapping[Key, V]) -> Iterable[tuple[Key, V]]:
    """Rows in key order, so two writers of many keys take their row locks in one order."""
    return sorted(rows.items(), key=lambda kv: tuple(str(k) for k in kv[0]))


def _unchanged(table: sa.Table, key_cols: list[str]) -> list[sa.ColumnElement[bool]]:
    """The row by key, still at the revision and deleted flag the pass read before asking the owner."""
    return [
        *[table.c[k] == sa.bindparam(f"k_{k}") for k in key_cols],
        table.c.revision == sa.bindparam("k_revision"),
        table.c.deleted == sa.bindparam("k_deleted", type_=sa.Boolean()),
    ]


def _was(key_cols: list[str], key: Key, before: Held) -> dict[str, object]:
    return {
        **{f"k_{c}": v for c, v in zip(key_cols, key, strict=True)},
        "k_revision": before.revision,
        "k_deleted": before.deleted,
    }


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
