"""files-service's tables are held to the caller's tenant and team by the database (c-415)

Revision ID: files_0011
Revises: files_0010

Every store query filtered by the tenant it was given, and nothing in the database stopped one that did not. Each
table now carries its generated policy (ops_store.schema.isolation_ddl) for the role every transaction runs as,
ops_files_tenant: a file, its blob, versions, references, holds and read requests to the transaction's team; the
upload keys, the storage settings, credentials and their audit, and the service event outbox to the tenant. The outbox
relay reads every tenant's events as ops_files_system (BYPASSRLS), granted the outbox alone.

file_versions, file_references and file_legal_holds take their file's team. A row whose file is gone (a released hold's
history, kept after the file was removed) takes NO_TEAM, which matches no team: only a tenant-wide transaction reads it.
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
    mssql_predicates_ddl,
    role_ddl,
    team_owned,
)

revision = "files_0011"
down_revision = "files_0010"
branch_labels = None
depends_on = None

CHAIN = "files"
ROLE = "ops_files_tenant"
SYSTEM_ROLE = "ops_files_system"
NO_TEAM = ""
TEAM_TABLES = ("files", "file_blobs", "file_versions", "file_references", "file_legal_holds", "file_read_requests")
TENANT_TABLES = (
    "file_idempotency",
    "storage_settings",
    "storage_credentials",
    "storage_settings_audit",
    "files_outbox",
)
CHILDREN = ("file_versions", "file_references", "file_legal_holds")
OUTBOX = "files_outbox"
# What the relay's role may do: read due events, mark them sent, prune old ones. Nothing else.
RELAY_GRANT = "SELECT, UPDATE, DELETE"


def _marked(name: str) -> sa.Table:
    info = {**TENANT_SCOPED, **team_owned("team")} if name in TEAM_TABLES else TENANT_SCOPED
    cols = [sa.Column("tenant_id", sa.String(64))] + ([sa.Column("team", sa.String(64))] if name in TEAM_TABLES else [])
    return sa.Table(name, sa.MetaData(), *cols, info=info)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    for name in CHILDREN:
        with op.batch_alter_table(name) as b:
            b.add_column(sa.Column("team", sa.String(64)))
        t = sa.table(name, sa.column("file_id", sa.String), sa.column("team", sa.String))
        f = sa.table("files", sa.column("id", sa.String), sa.column("team", sa.String))
        team = sa.select(f.c.team).where(f.c.id == t.c.file_id).scalar_subquery()
        op.execute(sa.update(t).values(team=sa.func.coalesce(team, NO_TEAM)))
        with op.batch_alter_table(name) as b:
            b.alter_column("team", existing_type=sa.String(64), nullable=False)
    tables = [_marked(n) for n in (*TEAM_TABLES, *TENANT_TABLES)]
    if dialect == "postgresql":
        op.execute(role_ddl(ROLE))
        op.execute(role_ddl(SYSTEM_ROLE, bypass=True))
        for t in tables:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t.name} TO {ROLE}")
        op.execute(f"GRANT {RELAY_GRANT} ON {OUTBOX} TO {SYSTEM_ROLE}")
        op.execute(f"GRANT USAGE ON SEQUENCE storage_settings_audit_id_seq TO {ROLE}")
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for t in tables:
        for statement in isolation_ddl(t, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in (*TEAM_TABLES, *TENANT_TABLES):
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
    if dialect == "postgresql":
        for name in (*TEAM_TABLES, *TENANT_TABLES):
            op.execute(f"REVOKE ALL ON {name} FROM {ROLE}")
        op.execute(f"REVOKE ALL ON {OUTBOX} FROM {SYSTEM_ROLE}")
        op.execute(f"REVOKE ALL ON SEQUENCE storage_settings_audit_id_seq FROM {ROLE}")
    for name in reversed(CHILDREN):
        with op.batch_alter_table(name) as b:
            b.drop_column("team")
