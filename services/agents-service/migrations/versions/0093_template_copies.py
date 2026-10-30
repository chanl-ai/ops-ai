"""Template copies (c-590)

Revision ID: 0093_template_copies
Revises: 0092_run_batches

A team installs a plugin's agent, skill or workflow as its own copy, made through the kind's create path. Where a copy
came from lives here, one row per copy in its team, so no agent, skill or workflow table changes. One live copy per
template version and team, held by a partial unique index; a deleted copy's row is marked removed. Carries the team
policy like every team-owned table. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0093_template_copies"
down_revision = "0092_run_batches"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
LIVE = sa.text("removed_at IS NULL")


def _marked() -> sa.Table:
    return sa.Table(
        "template_copies",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "template_copies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("record_id", sa.String(200), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("template_id", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("installed_by", sa.String(320), nullable=False),
        sa.Column("installed_at", sa.String(32), nullable=False),
        sa.Column("removed_at", sa.String(32)),
    )
    op.create_index(
        "uq_template_copies_live",
        "template_copies",
        ["tenant_id", "team_id", "source", "template_id", "version"],
        unique=True,
        postgresql_where=LIVE,
        mssql_where=LIVE,
    )
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [_marked()], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON template_copies TO {TENANT_ROLE}")
    for statement in isolation_ddl(_marked(), dialect, kind="team", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    op.drop_index("uq_template_copies_live", table_name="template_copies")
    op.drop_table("template_copies")
