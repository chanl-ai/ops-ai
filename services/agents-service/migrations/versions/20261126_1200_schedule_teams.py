"""workflow_schedules carries the team policy in place of the tenant one

Revision ID: 20261126_1200_schedule_teams
Revises: 20261124_2313_agent_instruction

A saved schedule was held to its tenant only, and each reader checked the team itself, so a new reader that forgot
showed another team's schedules. The table is now team-owned like the chain's other team tables: the store filters
every read by the acting team and the database's team policy does the same, while a tenant-wide block (the schedule
clock) still reads every team. Every row already names its workflow's team (team_id is NOT NULL), so no row moves.

The down path puts back the tenant policy 20261123_1900 made, as it made it: on PostgreSQL its own text, on SQL Server
the security policy over the chain's tenant predicates. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "20261126_1200_schedule_teams"
down_revision = "20261124_2313_agent_instruction"
branch_labels = None
depends_on = None

CHAIN = "agents"
SYSTEM_ROLE = "ops_runtime_system"
TABLE = "workflow_schedules"


def _marked(*, team: bool) -> sa.Table:
    """The table as far as its policy needs, as of this revision."""
    cols = [sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64))]
    return sa.Table(TABLE, sa.MetaData(), *cols, info={**TENANT_SCOPED, **TEAM_OWNED} if team else TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _policy(*, team: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in ("postgresql", "mssql"):
        return
    table = _marked(team=team)
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [table], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    for statement in isolation_ddl(table, dialect, kind="team" if team else "tenant", chain=CHAIN):
        op.execute(statement)


def upgrade() -> None:
    _policy(team=True)


# 20261123_1900's policy, word for word, so a downgrade leaves the schema as that revision left it.
TENANT_POLICY = (
    f"CREATE POLICY {TABLE}_tenant ON {TABLE} "
    "USING (tenant_id = current_setting('app.tenant_id', true)) "
    "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        _policy(team=False)
        return
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_isolation ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant ON {TABLE}")
    op.execute(TENANT_POLICY)
