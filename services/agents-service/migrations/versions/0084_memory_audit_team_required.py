"""Every memory audit row names its team (c-557)

Revision ID: 0084_memory_audit_team_required
Revises: 0083_memory_history

0083 marked memory_audit team-owned but left its team column nullable, so a row with no team escaped the team policy.
Rows written before 0083 take the team of the memory they name, else of another memory of the same person; a row
still without a team names neither (its memory and every other memory of that person are gone) and is dropped. SQL
Server binds the column in its security policy, so the policy is set aside around the change. Runs on PostgreSQL and
SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0084_memory_audit_team_required"
down_revision = "0083_memory_history"
branch_labels = None
depends_on = None

CHAIN = "agents"
SYSTEM_ROLE = "ops_runtime_system"


def _marked() -> sa.Table:
    return sa.Table(
        "memory_audit",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _required(nullable: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "mssql":
        for statement in isolation_ddl(_marked(), dialect, kind="tenant", chain=CHAIN):
            op.execute(statement)
    op.alter_column("memory_audit", "team_id", existing_type=sa.String(64), nullable=nullable)
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [_marked()], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
        for statement in isolation_ddl(_marked(), dialect, kind="team", chain=CHAIN):
            op.execute(statement)


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # The migrating role may own the table; FORCE row-level security would otherwise hide every row from it.
        op.execute("SET LOCAL row_security = off")
    op.execute(
        "UPDATE memory_audit SET team_id = (SELECT m.team_id FROM agent_memories m "
        "WHERE m.tenant_id = memory_audit.tenant_id AND m.id = memory_audit.memory_id) WHERE team_id IS NULL"
    )
    op.execute(
        "UPDATE memory_audit SET team_id = (SELECT MIN(m.team_id) FROM agent_memories m "
        "WHERE m.tenant_id = memory_audit.tenant_id AND m.person = memory_audit.person) WHERE team_id IS NULL"
    )
    op.execute("DELETE FROM memory_audit WHERE team_id IS NULL")
    _required(False)


def downgrade() -> None:
    _required(True)
