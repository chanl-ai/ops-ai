"""documents-service's tables are held to the caller's tenant and team by the database (c-415)

Revision ID: documents_0011
Revises: documents_0010

Every store query filtered by the tenant it was given, and nothing in the database stopped one that did not. Each
table now carries its generated policy (ops_store.schema.isolation_ddl) for the role every transaction runs as,
ops_documents_tenant: a document type, its versions, samples, tests and examples, an extraction and its corrections to
the transaction's team; layouts (read from bytes any team holding the file already has) and the service event outbox
to the tenant. ops_documents_system (BYPASSRLS) reads every tenant's outbox for the relay and the queued reads and tests
a restart picks up again, and nothing else.

document_type_versions and document_type_samples take their type's team, extraction_corrections their extraction's.
A row whose parent is gone takes NO_TEAM, which matches no team: only a tenant-wide transaction reads it.
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

revision = "documents_0011"
down_revision = "documents_0010"
branch_labels = None
depends_on = None

CHAIN = "documents"
ROLE = "ops_documents_tenant"
SYSTEM_ROLE = "ops_documents_system"
NO_TEAM = ""
TEAM_TABLES = (
    "document_types",
    "document_type_versions",
    "document_type_samples",
    "document_type_tests",
    "document_type_examples",
    "extractions",
    "extraction_corrections",
)
TENANT_TABLES = ("documents_layouts", "documents_outbox")
# Each child and the parent (table, key column) it takes its team from.
CHILDREN = {
    "document_type_versions": ("document_types", "type_id"),
    "document_type_samples": ("document_types", "type_id"),
    "extraction_corrections": ("extractions", "extraction_id"),
}
# What the system role reads: the relay's outbox (read, mark sent, prune) and the work a restart picks up.
SYSTEM_GRANTS = {
    "documents_outbox": "SELECT, UPDATE, DELETE",
    "extractions": "SELECT",
    "document_type_tests": "SELECT",
}


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
    for name, (parent, key) in CHILDREN.items():
        with op.batch_alter_table(name) as b:
            b.add_column(sa.Column("team", sa.String(64)))
        t = sa.table(name, sa.column("tenant_id", sa.String), sa.column(key, sa.String), sa.column("team", sa.String))
        p = sa.table(
            parent, sa.column("tenant_id", sa.String), sa.column("id", sa.String), sa.column("team", sa.String)
        )
        # A type's id is unique per tenant only, so the parent is matched on both.
        mine = sa.and_(p.c.tenant_id == t.c.tenant_id, p.c.id == t.c[key])
        team = sa.select(p.c.team).where(mine).scalar_subquery()
        op.execute(sa.update(t).values(team=sa.func.coalesce(team, NO_TEAM)))
        with op.batch_alter_table(name) as b:
            b.alter_column("team", existing_type=sa.String(64), nullable=False)
    tables = [_marked(n) for n in (*TEAM_TABLES, *TENANT_TABLES)]
    if dialect == "postgresql":
        op.execute(role_ddl(ROLE))
        op.execute(role_ddl(SYSTEM_ROLE, bypass=True))
        for t in tables:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t.name} TO {ROLE}")
        for name, grant in SYSTEM_GRANTS.items():
            op.execute(f"GRANT {grant} ON {name} TO {SYSTEM_ROLE}")
        op.execute(f"GRANT USAGE ON SEQUENCE extraction_corrections_id_seq TO {ROLE}")
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
        for name in SYSTEM_GRANTS:
            op.execute(f"REVOKE ALL ON {name} FROM {SYSTEM_ROLE}")
        op.execute(f"REVOKE ALL ON SEQUENCE extraction_corrections_id_seq FROM {ROLE}")
    for name in reversed(list(CHILDREN)):
        with op.batch_alter_table(name) as b:
            b.drop_column("team")
