"""A service's schema is its store metadata: every table, index, constraint and default its migrations create is also
in the SQLAlchemy tables its store defines, so DDL for any supported database is compiled from one source.

  sa.Table("cases", metadata, ..., info=TENANT_SCOPED)   # the database isolates this table by tenant
  differences(conn, [metadata])                           # every way the migrated database and the metadata differ
  unowned(conn, [metadata, ...])                          # tables in the database that no metadata defines

`TENANT_SCOPED` means the database itself hides other tenants' rows from this table (forced row-level security on
PostgreSQL, a security policy on SQL Server). DDL for that isolation is generated from the marker, so it is held equal
to what the database enforces: a marked table the database does not isolate, or the reverse, is a difference.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

TENANT_KEY = "tenant_scoped"
TENANT_SCOPED: dict[str, Any] = {TENANT_KEY: True}


def tenant_scoped(table: sa.Table) -> bool:
    return bool(table.info.get(TENANT_KEY))


def tables(metadatas: Iterable[sa.MetaData], exclude: Collection[str] = ()) -> dict[str, sa.Table]:
    return {name: t for m in metadatas for name, t in m.tables.items() if name not in exclude}


def isolated_tables(conn: sa.Connection) -> set[str]:
    """The tables the database isolates by tenant on its own, read from the database rather than from migrations."""
    if conn.dialect.name == "postgresql":
        # Forced, so the owner the services connect as is filtered too; enabled alone exempts the owner.
        rows = conn.execute(
            sa.text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p')"
                " AND c.relrowsecurity AND c.relforcerowsecurity"
            )
        )
        return {r[0] for r in rows}
    raise NotImplementedError(f"isolated_tables: no reader for {conn.dialect.name}")


def differences(conn: sa.Connection, metadatas: Sequence[sa.MetaData], exclude: Collection[str] = ()) -> list[str]:
    """Every way the database on `conn` differs from `metadatas` for the tables they define (less `exclude`), one line
    each: Alembic's comparison (tables, columns, types, nullability, indexes, unique keys, foreign keys), plus server
    defaults by presence, CHECK constraints and computed columns by name, and the tenant marker against isolation."""
    ours = tables(metadatas, exclude)

    def include(name: str | None, type_: str, _parent: dict[str, str | None]) -> bool:
        return type_ != "table" or name in ours

    context = MigrationContext.configure(
        conn,
        # Alembic's own default comparison fails on a computed column (its user hook reads `.arg` off a Computed), so
        # defaults are compared below from the inspector.
        opts={"compare_type": True, "compare_server_default": False, "include_name": include},
    )
    # Alembic compares a list of MetaData as one (as env.py's target_metadata), though the signature names one.
    out = [_describe(d) for d in compare_metadata(context, list(metadatas))]  # pyright: ignore[reportArgumentType]
    inspector = sa.inspect(conn)
    present = set(inspector.get_table_names())
    for name, table in sorted(ours.items()):
        if name not in present:
            continue  # compare_metadata reported it
        want = {c.name for c in table.constraints if isinstance(c, sa.CheckConstraint) and isinstance(c.name, str)}
        have = {str(c["name"]) for c in inspector.get_check_constraints(name)}
        out += [f"check {name}.{c} in the database, not in metadata" for c in sorted(have - want)]
        out += [f"check {name}.{c} in metadata, not in the database" for c in sorted(want - have)]
        reflected = {str(c["name"]): c for c in inspector.get_columns(name)}
        computed = {n for n, c in reflected.items() if c.get("computed")}
        declared = {c.name for c in table.columns if c.computed is not None}
        out += [f"computed column {name}.{c} differs" for c in sorted(computed ^ declared)]
        for column in table.columns:
            seen = reflected.get(column.name)
            if seen is None or column.name in computed | declared:
                continue
            # Only presence: each database renders a default's text its own way. A sequence is the key's, not a default.
            db_default = seen.get("default")
            has = db_default is not None and not str(db_default).startswith("nextval(")
            if has != (column.server_default is not None):
                where = "the database" if has else "metadata"
                out.append(f"default {name}.{column.name} only in {where}")
    isolated = isolated_tables(conn) & set(ours)
    marked = {name for name, t in ours.items() if tenant_scoped(t)}
    out += [f"tenant {t} is isolated in the database, not marked TENANT_SCOPED" for t in sorted(isolated - marked)]
    out += [f"tenant {t} is marked TENANT_SCOPED, not isolated in the database" for t in sorted(marked - isolated)]
    return out


def unowned(conn: sa.Connection, metadatas: Sequence[sa.MetaData], exclude: Collection[str] = ()) -> list[str]:
    """Tables in the database that no metadata defines, besides Alembic's version tables and `exclude`."""
    known = tables(metadatas)
    return sorted(
        name
        for name in sa.inspect(conn).get_table_names()
        if name not in known and name not in exclude and not name.startswith("alembic_version")
    )


def _describe(diff: Any) -> str:
    """One line for one of Alembic's difference tuples (or a list of column modifications)."""
    if isinstance(diff, list):
        return "; ".join(_describe(d) for d in diff)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    kind, *rest = diff
    where = ""
    for part in rest:
        if isinstance(part, sa.Table):
            where = part.name
        elif isinstance(part, sa.Index):
            where = f"{part.table.name if part.table is not None else ''}.{part.name}"
        elif isinstance(part, (sa.Column, sa.Constraint)):
            where = f"{part.table.name}.{part.name}"
        elif isinstance(part, str) and not where:
            where = part
    if kind.startswith("modify_") and len(rest) >= 3:
        table, column = rest[1], rest[2]
        return f"{kind} {table}.{column}: database {rest[-2]!r}, metadata {rest[-1]!r}"
    side = "in metadata, not in the database" if kind.startswith("add_") else "in the database, not in metadata"
    return f"{kind} {where} {side}"
