"""file_watches and file_watch_events: a team watches places of a connection, and each check's findings are numbered

A watch keeps the picked places, where the last check stopped and a lease while a check runs; its events (new,
changed, renamed, removed, failed) are numbered by the lease holder so a reader follows them in order, and are kept
90 days. A source file records its watch, the listing's marker and how many checks in a row found it gone, so a full
listing removes only its own watch's files. Both tables are held to the caller's team; the check process and the
retention sweep read across tenants as ops_files_system. Runs on PostgreSQL and SQL Server.

Revision ID: 20261124_0010_file_watches
Revises: 20261123_2345_source_files
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TENANT_SCOPED,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_drop_default_ddl,
    mssql_predicates_ddl,
    team_owned,
)

revision = "20261124_0010_file_watches"
down_revision = "20261123_2345_source_files"
branch_labels = None
depends_on = None

CHAIN = "files"
ROLE = "ops_files_tenant"
SYSTEM_ROLE = "ops_files_system"
TABLES = ("file_watches", "file_watch_events")


def _marked(name: str) -> sa.Table:
    cols = [sa.Column("tenant_id", sa.String(64)), sa.Column("team", sa.String(64))]
    return sa.Table(name, sa.MetaData(), *cols, info={**TENANT_SCOPED, **team_owned("team")})


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    with op.batch_alter_table("files") as b:
        b.add_column(sa.Column("watch_id", sa.String(64)))
        b.add_column(sa.Column("source_marker", sa.String(200)))
        b.add_column(sa.Column("gone_count", sa.Integer, nullable=False, server_default="0"))
    op.create_table(
        "file_watches",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("team", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("plugin", sa.String(120), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("connection_id", sa.String(64)),
        sa.Column("values", sa.JSON, nullable=False),
        sa.Column("place", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("check_requested_at", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_outcome", sa.JSON),
        sa.Column("next_event", sa.Integer, nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index("ix_file_watches_requested", "file_watches", ["check_requested_at"])
    op.create_table(
        "file_watch_events",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("watch_id", sa.String(64), nullable=False),
        sa.Column("number", sa.Integer, nullable=False, autoincrement=False),
        sa.Column("team", sa.String(64), nullable=False),
        sa.Column("file_id", sa.String(64)),
        sa.Column("version", sa.Integer),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(500)),
        sa.Column("size", sa.BigInteger),
        sa.Column("path", sa.String(1024)),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "watch_id", "number"),
    )
    op.create_index("ix_file_watch_events_at", "file_watch_events", ["at"])
    tables = [_marked(n) for n in TABLES]
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=None):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        for name in TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {ROLE}")
        # The check process lists watches with a check asked for; the retention sweep deletes old events.
        op.execute(f"GRANT SELECT ON file_watches TO {SYSTEM_ROLE}")
        op.execute(f"GRANT SELECT, DELETE ON file_watch_events TO {SYSTEM_ROLE}")
    for t in tables:
        for statement in isolation_ddl(t, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in TABLES:
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
    op.drop_table("file_watch_events")
    op.drop_table("file_watches")
    if dialect == "mssql":
        # SQL Server refuses to drop a column while its default constraint is bound to it.
        op.execute(mssql_drop_default_ddl("files", "gone_count"))
    with op.batch_alter_table("files") as b:
        for name in ("gone_count", "source_marker", "watch_id"):
            b.drop_column(name)
