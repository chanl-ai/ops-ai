"""The places PostgreSQL and SQL Server differ, each written once (c-343; decisions/database-support.md). Stores
build every statement with SQLAlchemy Core and reach for one of these where Core has no portable form. Each renders
for postgresql, mssql and sqlite (the unit tests' database); any other dialect is refused.

  q = locked(sa.select(t).where(t.c.id == i), t)                 # a row lock held to the end of the transaction
  q = claim(sa.select(t).where(due).order_by(t.c.due).limit(1), t)   # a queue claim: skips rows another holds
  await conn.execute(upsert(conn, t, row, keys=["id"]))           # insert, or update the row with the same key
  await conn.execute(insert_ignore(conn, t, row, keys=["id"]))    # insert unless a row with the same key exists
  await lock_key(conn, f"thread:{thread_id}")                     # one writer per key until the transaction ends
  t.c.due_at <= db_now(); db_epoch(); db_after(seconds)           # the database's clock, never the host's
  async with tenant_tx(engine, tenant, role=...) as conn: ...     # the tenant the database isolates rows by

`with_for_update()` alone renders nothing on SQL Server, so a lock taken that way vanishes there with no error; the
portability check refuses it outside this package.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import mssql, postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import FunctionElement

SUPPORTED = ("postgresql", "mssql", "sqlite")
Bind = sa.Connection | sa.Engine | AsyncConnection | AsyncEngine | sa.Dialect


def dialect_of(bind: Bind) -> str:
    name = bind.name if isinstance(bind, sa.Dialect) else bind.dialect.name
    if name not in SUPPORTED:
        raise NotImplementedError(f"ops_store.dialect: {name} is not a supported database ({', '.join(SUPPORTED)})")
    return name


# Row locks and queue claims ---------------------------------------------------------------------------------------

_ROW_LOCK = "WITH (UPDLOCK, ROWLOCK)"
_CLAIM_LOCK = "WITH (UPDLOCK, ROWLOCK, READPAST)"


def locked[S: sa.Select[Any]](query: S, table: sa.FromClause) -> S:
    """`query` with the rows it reads from `table` locked until the transaction ends: FOR UPDATE on PostgreSQL,
    UPDLOCK and ROWLOCK on SQL Server. Both forms are attached; each dialect renders only its own."""
    return query.with_for_update().with_hint(table, _ROW_LOCK, "mssql")


def claim[S: sa.Select[Any]](query: S, table: sa.FromClause) -> S:
    """A queue claim: like `locked`, and rows another transaction holds are skipped rather than waited for (SKIP
    LOCKED, READPAST). `query` orders and limits its rows itself, so the oldest due row is taken first everywhere."""
    return query.with_for_update(skip_locked=True).with_hint(table, _CLAIM_LOCK, "mssql")


async def lock_key(conn: AsyncConnection, key: str) -> None:
    """Serialises every transaction that locks `key` until it ends: an advisory lock on PostgreSQL, an application
    lock on SQL Server. SQLite runs one writer at a time, so it needs none."""
    match dialect_of(conn):
        case "postgresql":
            await conn.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(key, 0))))
        case "mssql":
            # sp_getapplock answers below zero when it did not get the lock; THROW turns that into an error.
            await conn.execute(
                sa.text(
                    "DECLARE @granted int; EXEC @granted = sp_getapplock @Resource = :key, @LockMode = 'Exclusive', "
                    "@LockOwner = 'Transaction', @LockTimeout = -1; "
                    "IF @granted < 0 THROW 51000, 'ops_store.lock_key: lock not granted', 1;"
                ),
                {"key": key[:255]},
            )
        case _:
            return


# Upserts ----------------------------------------------------------------------------------------------------------


def upsert(
    bind: Bind,
    table: sa.Table,
    values: Mapping[str, Any],
    *,
    keys: Sequence[str],
    update: Sequence[str] | None = None,
    returning: Sequence[str] = (),
) -> sa.Executable:
    """Inserts `values`, or updates the row whose `keys` match: `update` names the columns to overwrite (default: every
    column given that is not a key). ON CONFLICT on PostgreSQL and SQLite, MERGE WITH (HOLDLOCK) on SQL Server, which
    holds the key range so two concurrent upserts of one key never both insert."""
    changed = [c for c in (update if update is not None else values) if c not in keys]
    name = dialect_of(bind)
    if name == "mssql":
        return _merge(table, values, keys=keys, changed=changed, returning=returning)
    stmt = (postgresql.insert(table) if name == "postgresql" else sqlite.insert(table)).values(dict(values))
    if changed:
        done = stmt.on_conflict_do_update(index_elements=list(keys), set_={c: stmt.excluded[c] for c in changed})
    else:
        done = stmt.on_conflict_do_nothing(index_elements=list(keys))
    return done.returning(*[table.c[c] for c in returning]) if returning else done


def insert_ignore(bind: Bind, table: sa.Table, values: Mapping[str, Any], *, keys: Sequence[str]) -> sa.Executable:
    """Inserts `values` unless a row with the same `keys` exists; neither an error nor an update when one does."""
    if dialect_of(bind) != "mssql":
        return upsert(bind, table, values, keys=keys, update=[])
    cols = list(values)
    row = sa.select(*[sa.literal(values[c], table.c[c].type).label(c) for c in cols])
    # UPDLOCK and HOLDLOCK keep the key range locked from the check to the insert, so a concurrent insert waits.
    taken = (
        sa.select(sa.literal(1))
        .select_from(table)
        .where(*[table.c[k] == sa.literal(values[k], table.c[k].type) for k in keys])
        .with_hint(table, "WITH (UPDLOCK, HOLDLOCK)", "mssql")
    )
    return table.insert().from_select(cols, row.where(~sa.exists(taken)))


def _merge(
    table: sa.Table,
    values: Mapping[str, Any],
    *,
    keys: Sequence[str],
    changed: Sequence[str],
    returning: Sequence[str],
) -> sa.TextClause:
    prep = mssql.dialect().identifier_preparer
    q = prep.quote
    cols = list(values)
    source = ", ".join(f":v_{i}" for i in range(len(cols)))
    names = ", ".join(q(c) for c in cols)
    on = " AND ".join(f"t.{q(k)} = s.{q(k)}" for k in keys)
    parts = [
        f"MERGE INTO {prep.format_table(table)} WITH (HOLDLOCK) AS t",
        f"USING (VALUES ({source})) AS s ({names})",
        f"ON {on}",
    ]
    if changed:
        parts.append("WHEN MATCHED THEN UPDATE SET " + ", ".join(f"t.{q(c)} = s.{q(c)}" for c in changed))
    parts.append(f"WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({', '.join(f's.{q(c)}' for c in cols)})")
    if returning:
        parts.append("OUTPUT " + ", ".join(f"inserted.{q(c)}" for c in returning))
    params = [sa.bindparam(f"v_{i}", values[c], type_=table.c[c].type) for i, c in enumerate(cols)]
    text = sa.text(" ".join(parts) + ";").bindparams(*params)
    if returning:
        return text.columns(*[table.c[c] for c in returning])  # pyright: ignore[reportReturnType]
    return text


# The database's clock ---------------------------------------------------------------------------------------------


class db_now(FunctionElement[Any]):  # noqa: N801 - read as a function in a query
    """The database's current time with its offset: now() on PostgreSQL, SYSDATETIMEOFFSET() on SQL Server.
    `func.now()` renders CURRENT_TIMESTAMP on SQL Server, the server's local time with no offset."""

    type = sa.DateTime(timezone=True)
    inherit_cache = True


class db_epoch(FunctionElement[float]):  # noqa: N801
    """Seconds since 1970 on the database's clock, as a float."""

    type = sa.Float()
    inherit_cache = True


class db_after(FunctionElement[Any]):  # noqa: N801
    """The database's current time plus a number of seconds (a float expression or value)."""

    type = sa.DateTime(timezone=True)
    inherit_cache = True


@compiles(db_now, "postgresql")
def _now_pg(_e: db_now, _c: SQLCompiler, **_kw: Any) -> str:
    return "now()"


@compiles(db_now, "mssql")
def _now_mssql(_e: db_now, _c: SQLCompiler, **_kw: Any) -> str:
    return "SYSDATETIMEOFFSET()"


@compiles(db_now)
def _now_other(_e: db_now, _c: SQLCompiler, **_kw: Any) -> str:
    return "CURRENT_TIMESTAMP"


@compiles(db_epoch, "postgresql")
def _epoch_pg(_e: db_epoch, _c: SQLCompiler, **_kw: Any) -> str:
    return "extract(epoch from now())"


@compiles(db_epoch, "mssql")
def _epoch_mssql(_e: db_epoch, _c: SQLCompiler, **_kw: Any) -> str:
    return "(CAST(DATEDIFF_BIG(millisecond, '1970-01-01', SYSUTCDATETIME()) AS FLOAT) / 1000.0)"


@compiles(db_epoch)
def _epoch_other(_e: db_epoch, _c: SQLCompiler, **_kw: Any) -> str:
    return "((julianday('now') - 2440587.5) * 86400.0)"


@compiles(db_after, "postgresql")
def _after_pg(e: db_after, c: SQLCompiler, **kw: Any) -> str:
    return f"(now() + make_interval(secs => {c.process(_seconds(e), **kw)}))"


@compiles(db_after, "mssql")
def _after_mssql(e: db_after, c: SQLCompiler, **kw: Any) -> str:
    return f"DATEADD(millisecond, CAST(({c.process(_seconds(e), **kw)}) * 1000 AS BIGINT), SYSDATETIMEOFFSET())"


@compiles(db_after)
def _after_other(e: db_after, c: SQLCompiler, **kw: Any) -> str:
    return f"datetime('now', printf('%+f seconds', {c.process(_seconds(e), **kw)}))"


def _seconds(e: db_after) -> ColumnElement[Any]:
    (seconds,) = e.clauses.clauses
    return seconds  # pyright: ignore[reportReturnType]


# Tenant transactions ----------------------------------------------------------------------------------------------

TENANT_SETTING = "app.tenant_id"
TENANT_CONTEXT = "tenant_id"


async def enter_tenant(conn: AsyncConnection, tenant_id: str | None, *, role: str | None = None) -> None:
    """Tells the database which tenant this transaction acts for, so its row-level security (PostgreSQL) or security
    policy (SQL Server) shows that tenant's rows only; None shows none. PostgreSQL scopes both to the transaction;
    SQL Server's session context outlives it, so `tenant_tx` clears it before the connection goes back to the pool."""
    match dialect_of(conn):
        case "postgresql":
            if role:
                await conn.execute(sa.text(f"SET LOCAL ROLE {_pg_role(role)}"))
            await conn.execute(sa.select(sa.func.set_config(TENANT_SETTING, tenant_id or "", True)))
        case "mssql":
            await conn.execute(
                sa.text("EXEC sp_set_session_context @key = :k, @value = :v"), {"k": TENANT_CONTEXT, "v": tenant_id}
            )
        case _:
            return


async def leave_tenant(conn: AsyncConnection) -> None:
    if dialect_of(conn) == "mssql":
        await conn.execute(sa.text("EXEC sp_set_session_context @key = :k, @value = NULL"), {"k": TENANT_CONTEXT})


@asynccontextmanager
async def tenant_tx(
    engine: AsyncEngine, tenant_id: str | None, *, role: str | None = None
) -> AsyncGenerator[AsyncConnection]:
    """One transaction acting for `tenant_id`, with the tenant cleared when it ends however it ends."""
    async with engine.connect() as conn:
        try:
            async with conn.begin():
                await enter_tenant(conn, tenant_id, role=role)
                yield conn
        finally:
            await leave_tenant(conn)
            if conn.in_transaction():
                await conn.commit()


@asynccontextmanager
async def system_tx(engine: AsyncEngine, *, role: str | None = None) -> AsyncGenerator[AsyncConnection]:
    """One transaction as `role`, which reads other tenants' rows of what it is granted, for work claimed before its
    tenant is known. PostgreSQL switches to it (a BYPASSRLS role); SQL Server impersonates the database user of that
    name (EXECUTE AS USER), which the read predicates pass and its grants limit, table by table and column by column
    (deploy/database/mssql.py). The impersonation outlives the transaction, so it is reverted however it ends."""
    async with engine.connect() as conn:
        impersonating = False
        try:
            async with conn.begin():
                match dialect_of(conn):
                    case "postgresql":
                        if role:
                            await conn.execute(sa.text(f"SET LOCAL ROLE {_pg_role(role)}"))
                    case "mssql":
                        if role:
                            await conn.execute(sa.text(f"EXECUTE AS USER = N'{_ms_user(role)}'"))
                            impersonating = True
                    case _:
                        pass
                yield conn
        finally:
            if impersonating:
                await conn.execute(sa.text("REVERT"))
            if conn.in_transaction():
                await conn.commit()


def _ms_user(name: str) -> str:
    """A user name for EXECUTE AS, which takes a literal: a code constant, refused if it could close the quote."""
    if not name.replace("_", "").isalnum():
        raise ValueError(f"{name!r} is not a database user name")
    return name


def _pg_role(role: str) -> str:
    return postgresql.dialect().identifier_preparer.quote(role)


# Full-text --------------------------------------------------------------------------------------------------------


def full_text(bind: Bind, column: sa.ColumnElement[Any], query: str) -> sa.ColumnElement[bool]:
    """Rows whose full-text `column` matches the words in `query`: a tsvector match on PostgreSQL, CONTAINS over a
    full-text index on SQL Server. Ranking differs by database and stays with the store that ranks."""
    match dialect_of(bind):
        case "postgresql":
            return column.op("@@")(sa.func.plainto_tsquery("simple", query))
        case "mssql":
            # Each word quoted, so a word that is a CONTAINS operator (AND, NEAR) is searched for, not obeyed.
            words = " AND ".join(f'"{w}"' for w in query.replace('"', " ").split()) or '""'
            return _Contains(column, sa.bindparam(None, words, type_=sa.String()))
        case _:
            return sa.func.lower(column).contains(query.lower())


class _Contains(ColumnElement[bool]):
    """SQL Server's CONTAINS, a predicate rather than a function: it cannot be compared to 1 as a bit would be."""

    inherit_cache = True

    def __init__(self, column: sa.ColumnElement[Any], words: sa.BindParameter[str]) -> None:
        self.column, self.words = column, words


@compiles(_Contains)
def _contains(e: _Contains, c: SQLCompiler, **kw: Any) -> str:
    return f"CONTAINS({c.process(e.column, **kw)}, {c.process(e.words, **kw)})"


__all__ = [
    "claim",
    "db_after",
    "db_epoch",
    "db_now",
    "dialect_of",
    "enter_tenant",
    "full_text",
    "insert_ignore",
    "leave_tenant",
    "lock_key",
    "locked",
    "system_tx",
    "tenant_tx",
    "upsert",
]
