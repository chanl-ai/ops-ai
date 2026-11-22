"""Each workflow's working copy in a table of its own

Revision ID: 0121_engine_working_copies
Revises: 0120_skill_step_tools

The workflow editor saved every change as a new version, so a half-made workflow could not be kept and every save
added a number to the history. `engine_working_copies` holds one mutable copy per workflow: the definition as the
editor last saved it, its digest, the version it started from, the checks of that save, and who saved it when.
Publishing makes the next version from it and removes the row (ops_engine store/definitions.py). The table starts
empty; nothing is moved into it.

Tenant-scoped like engine_definitions, whose nullable team it copies. The down path drops the table and its policy;
an unpublished working copy is lost, and every version stays.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "0121_engine_working_copies"
down_revision = "0120_skill_step_tools"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLE = "engine_working_copies"


def _marked() -> sa.Table:
    """The table as far as its policy needs, as of this revision."""
    return sa.Table(TABLE, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64)),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("updated_by", sa.String(200), nullable=False),
    )
    if dialect not in ("postgresql", "mssql"):
        return
    table = _marked()
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [table], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    else:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {TENANT_ROLE}")
    for statement in isolation_ddl(table, dialect, kind="tenant", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked(), dialect):
            op.execute(statement)
    op.drop_table(TABLE)
