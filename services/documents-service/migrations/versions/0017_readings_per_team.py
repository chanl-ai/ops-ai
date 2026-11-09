"""Readings belong to a team

Revision ID: documents_0017
Revises: documents_0016

documents_0016 kept one reading per tenant and file digest, held to the tenant only, so any team of the tenant could
read a reading made from another team's file. A reading is now the team's own, like every other record of this chain:
the team joins the key of documents_readings and documents_reading_pages (which gains the column), and all three
readings tables carry the team policy in place of the tenant one.

Existing readings go to the team that asked for them, and each other team holding a file of the same bytes gets a copy
of the reading and its pages, naming that team's own file, so no team loses a finished or queued reading. A page whose
reading is gone has no team and is dropped. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl, team_owned

revision = "documents_0017"
down_revision = "documents_0016"
branch_labels = None
depends_on = None

CHAIN = "documents"
TABLES = ("documents_readings", "documents_reading_pages", "documents_reading_files")
KEY = "tenant_id, file_digest, reader_version, settings_key"
READING_COLUMNS = (
    "status, pages_total, pages_done, facts, error_code, error, attempts, actor, duration_ms, created_at, "
    "started_at, finished_at"
)
SAME_KEY = " AND ".join(f"o.{c} = {{t}}.{c}" for c in KEY.split(", "))


def _marked(name: str, *, team: bool) -> sa.Table:
    cols = [sa.Column("tenant_id", sa.String(64)), sa.Column("team", sa.String(64))]
    return sa.Table(name, sa.MetaData(), *cols, info={**TENANT_SCOPED, **team_owned("team")} if team else TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _drop_primary_key(table: str, dialect: str) -> None:
    if dialect == "mssql":
        # A key made by create_table without a name has a generated name on SQL Server.
        op.execute(
            f"DECLARE @n sysname = (SELECT name FROM sys.key_constraints WHERE type = 'PK' "
            f"AND parent_object_id = OBJECT_ID(N'{table}')); "
            f"IF @n IS NOT NULL EXEC (N'ALTER TABLE {table} DROP CONSTRAINT ' + QUOTENAME(@n))"
        )
    else:
        op.drop_constraint(f"{table}_pkey", table, type_="primary")


def _policies(*, team: bool) -> None:
    dialect = op.get_bind().dialect.name
    tables = [_marked(n, team=team) for n in TABLES]
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=None):
            op.execute(statement)
    for t in tables:
        for statement in isolation_ddl(t, dialect, kind="team" if team else "tenant", chain=CHAIN):
            op.execute(statement)


def _unlock() -> str:
    dialect = op.get_bind().dialect.name
    if dialect not in ("postgresql", "mssql"):
        raise NotImplementedError(f"documents_0017 runs on PostgreSQL and SQL Server, not {dialect}")
    if dialect == "postgresql":
        # The migrating role may own the tables; with FORCE on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    for name in TABLES:
        for statement in isolation_drop_ddl(_marked(name, team=False), dialect):
            op.execute(statement)
    _drop_primary_key("documents_readings", dialect)
    _drop_primary_key("documents_reading_pages", dialect)
    return dialect


def upgrade() -> None:
    _unlock()
    op.add_column("documents_reading_pages", sa.Column("team", sa.String(64)))
    op.execute(
        "UPDATE documents_reading_pages SET team = (SELECT o.team FROM documents_readings o "
        f"WHERE {SAME_KEY.format(t='documents_reading_pages')})"
    )
    op.execute("DELETE FROM documents_reading_pages WHERE team IS NULL")
    # One holder per other team of the same bytes: its first file is the one a queued read reads as.
    holders = (
        "(SELECT tenant_id, file_digest, team, MIN(file_id) AS file_id FROM documents_reading_files "
        "GROUP BY tenant_id, file_digest, team)"
    )
    op.execute(
        f"INSERT INTO documents_reading_pages ({KEY}, page, body, team) "
        f"SELECT {', '.join('p.' + c for c in KEY.split(', '))}, p.page, p.body, h.team "
        f"FROM documents_reading_pages p JOIN {holders} h "
        "ON h.tenant_id = p.tenant_id AND h.file_digest = p.file_digest AND h.team <> p.team"
    )
    op.execute(
        f"INSERT INTO documents_readings ({KEY}, {READING_COLUMNS}, team, file_id) "
        f"SELECT {', '.join('r.' + c for c in (*KEY.split(', '), *READING_COLUMNS.split(', ')))}, h.team, h.file_id "
        f"FROM documents_readings r JOIN {holders} h "
        "ON h.tenant_id = r.tenant_id AND h.file_digest = r.file_digest AND h.team <> r.team"
    )
    op.alter_column("documents_reading_pages", "team", existing_type=sa.String(64), nullable=False)
    op.create_primary_key(
        "documents_readings_pkey",
        "documents_readings",
        ["tenant_id", "team", "file_digest", "reader_version", "settings_key"],
    )
    op.create_primary_key(
        "documents_reading_pages_pkey",
        "documents_reading_pages",
        ["tenant_id", "team", "file_digest", "reader_version", "settings_key", "page"],
    )
    _policies(team=True)


def downgrade() -> None:
    """Back to one reading per tenant and bytes: the copy of the first team (by name) stays."""
    _unlock()
    for name in ("documents_reading_pages", "documents_readings"):
        page = " AND o.page = {t}.page" if name == "documents_reading_pages" else ""
        op.execute(
            f"DELETE FROM {name} WHERE EXISTS (SELECT 1 FROM {name} o WHERE {SAME_KEY.format(t=name)}"
            f"{page.format(t=name)} AND o.team < {name}.team)"
        )
    op.drop_column("documents_reading_pages", "team")
    op.create_primary_key(
        "documents_readings_pkey", "documents_readings", ["tenant_id", "file_digest", "reader_version", "settings_key"]
    )
    op.create_primary_key(
        "documents_reading_pages_pkey",
        "documents_reading_pages",
        ["tenant_id", "file_digest", "reader_version", "settings_key", "page"],
    )
    _policies(team=False)
