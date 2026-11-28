"""Each workspace's list of agent instruction sections in a table of its own

Revision ID: 20261124_2313_agent_instruction
Revises: 20261124_1100_agents_outbox

The sections an agent's brief may carry (their labels, hints, order, which are hidden) are a workspace setting an
admin edits. `agent_instruction_sections` holds one row per tenant with the list as saved, who saved it and when. No
row means the workspace uses the default list, which the service defines; resetting the list deletes the row. The
table starts empty, and no stored agent is rewritten: a saved agent keeps the prompt compiled when it was saved.

Tenant-scoped, with the tenant policy every tenant table of this chain carries. The down path drops the table and its
policy; a workspace's edited list is lost and every workspace reads the default list again. Runs on PostgreSQL and
SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "20261124_2313_agent_instruction"
down_revision = "20261124_1100_agents_outbox"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLE = "agent_instruction_sections"


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
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
