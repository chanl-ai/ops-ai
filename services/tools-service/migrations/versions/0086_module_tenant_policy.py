"""module_tenant_policy: tool_modules is held to its tenant by the database

tool_modules was the one tools table with no row policy, so a statement that named no tenant read every tenant's
modules. It now carries the generated tenant policy (ops_store.schema.isolation_ddl) for ops_tools_tenant, the role
every store transaction runs as. The policy is by tenant, not by team: a module with no team is read by every team, a
module granted to another team's workflow is read by that team, and a call resolves its module across teams, so the
store names the team in code (store/modules.py `team_modules`, `granted`).

No backfill: every row carries its tenant in its key. The tenant role holds its grants since tools_0081, and on SQL
Server the tools tenant predicate functions already pass the tools system user (tools_0081); they are made here only
where missing. Each step is safe to re-run. Downgrade removes the policy and row-level security from the table.

Revision ID: tools_0086_module_tenant_policy
Revises: tools_0085_module_list_indexes
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "tools_0086_module_tenant_policy"
down_revision = "tools_0085_module_list_indexes"
branch_labels = None
depends_on = None

CHAIN = "tools"
SYSTEM_ROLE = "ops_tools_system"
TABLE = sa.Table("tool_modules", sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [TABLE], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    for statement in isolation_ddl(TABLE, dialect, chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(TABLE, dialect):
            op.execute(statement)
