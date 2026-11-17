"""This service's copy of tools-service's tool catalogue

Revision ID: 0116_tool_catalog_copies
Revises: 0115_workflow_list_columns

`GET /v1/tools` asked tools-service for the catalogue on every request and paged it in Python. tools-service now
reports each module and team grant change as an event and pages its catalogue for a resync, so this service keeps a
copy (store/tool_copies.py, `ops_store.copies`): `tool_catalog` (one row per module, tenant policy), its operations in
`tool_catalog_operations` (tenant policy) and `tool_team_state` (one team's grant of a module it does not own, team
policy). The tables start empty and the resync fills them, so there is nothing to backfill.

The down path drops the three tables and their policies. They hold copies only: upgrading again makes them empty,
and the worker's resync, which reads tools-service's full catalogue when it starts and every pass after, with no
marker to reset (`ops_store.copies.resync`), fills them again. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "0116_tool_catalog_copies"
down_revision = "0115_workflow_list_columns"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
# Table -> whether its policy is a team's (else the tenant's).
TABLES = {"tool_catalog": False, "tool_catalog_operations": False, "tool_team_state": True}


def _marked(name: str, *, team: bool) -> sa.Table:
    """The table as far as its policy needs, as of this revision."""
    columns = [sa.Column("tenant_id", sa.String(64)), *([sa.Column("team_id", sa.String(64))] if team else [])]
    return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED} if team else TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _copy_columns() -> list[sa.Column[Any]]:
    """The columns every `ops_store.copies` table has after its keys."""
    return [
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.Float(), nullable=True),
    ]


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "tool_catalog",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(200), primary_key=True),
        *_copy_columns(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("app", sa.String(200), nullable=True),
        sa.Column("owner_team", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("version", sa.String(64), nullable=True),
    )
    op.create_index("ix_tool_catalog_owner_team", "tool_catalog", ["tenant_id", "owner_team"])
    op.create_table(
        "tool_catalog_operations",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("module_id", sa.String(200), primary_key=True),
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("access", sa.String(16), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_tool_catalog_operations_name", "tool_catalog_operations", ["tenant_id", "name", "module_id", "id"]
    )
    op.create_table(
        "tool_team_state",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(200), primary_key=True),
        *_copy_columns(),
        sa.Column("module_id", sa.String(200), nullable=False),
        sa.Column("via", sa.String(32), nullable=False),
        sa.Column("operations", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=True),
    )
    op.create_index("ix_tool_team_state_module", "tool_team_state", ["tenant_id", "team_id", "module_id"])
    if dialect not in ("postgresql", "mssql"):
        return
    tables = [_marked(name, team=team) for name, team in TABLES.items()]
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    else:
        for name in TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {TENANT_ROLE}")
    for table, team in zip(tables, TABLES.values(), strict=True):
        for statement in isolation_ddl(table, dialect, kind="team" if team else "tenant", chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name, team in TABLES.items():
            for statement in isolation_drop_ddl(_marked(name, team=team), dialect):
                op.execute(statement)
    op.drop_index("ix_tool_team_state_module", table_name="tool_team_state")
    op.drop_table("tool_team_state")
    op.drop_index("ix_tool_catalog_operations_name", table_name="tool_catalog_operations")
    op.drop_table("tool_catalog_operations")
    op.drop_index("ix_tool_catalog_owner_team", table_name="tool_catalog")
    op.drop_table("tool_catalog")
