"""Template copies (c-590)

Revision ID: documents_0014
Revises: documents_0013

A team installs a plugin's document type as its own copy, made through the type's create path. Where a copy came from
lives here, one row per copy in its team, so no document type table changes. agents-service's chain already has a
`template_copies` table in the same database, so this one is `documents_template_copies`. One live copy per template
version and team, held by a partial unique index; a deleted copy's row is marked removed. Carries the team policy like
every team-owned table of this chain, for ops_documents_tenant; the system role reads none of it. Runs on PostgreSQL
and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl, team_owned

revision = "documents_0014"
down_revision = "documents_0013"
branch_labels = None
depends_on = None

CHAIN = "documents"
ROLE = "ops_documents_tenant"
LIVE = sa.text("removed_at IS NULL")


def _marked() -> sa.Table:
    return sa.Table(
        "documents_template_copies",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team", sa.String(64)),
        info={**TENANT_SCOPED, **team_owned("team")},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "documents_template_copies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("record_id", sa.String(200), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("template_id", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64)),
        sa.Column("installed_by", sa.String(320), nullable=False),
        sa.Column("installed_at", sa.String(32), nullable=False),
        sa.Column("removed_at", sa.String(32)),
    )
    op.create_index(
        "uq_documents_template_copies_live",
        "documents_template_copies",
        ["tenant_id", "team", "source", "template_id", "version"],
        unique=True,
        postgresql_where=LIVE,
        mssql_where=LIVE,
    )
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [_marked()], column_type=_column_type, system_user=None):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON documents_template_copies TO {ROLE}")
    for statement in isolation_ddl(_marked(), dialect, kind="team", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    op.drop_index("uq_documents_template_copies_live", table_name="documents_template_copies")
    op.drop_table("documents_template_copies")
