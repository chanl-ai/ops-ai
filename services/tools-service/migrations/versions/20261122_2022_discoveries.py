"""tool_discoveries and tool_discovery_operations: what a discovery found, kept 24 hours for the picker

POST /v1/tool-modules/discover answered every operation a source listed in one reply, and the console's picker
searched them in the browser. A discovery is now stored for the person who asked, with each operation's name,
description, access, method, path, group and input (never its headers, body or example answer), and the picker pages
and searches it in SQL. Both tables are held to their tenant and team by the generated policy for ops_tools_tenant on
both databases. A new discovery deletes the team's expired ones.

No backfill: a discovery lives 24 hours and nothing older exists. Downgrade drops the policies and both tables.

Revision ID: 20261122_2022_discoveries
Revises: tools_0088_app_card_account
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "20261122_2022_discoveries"
down_revision = "tools_0088_app_card_account"
branch_labels = None
depends_on = None

CHAIN = "tools"
ROLE = "ops_tools_tenant"
SYSTEM_ROLE = "ops_tools_system"
DISCOVERIES = "tool_discoveries"
OPERATIONS = "tool_discovery_operations"


def _marked() -> list[sa.Table]:
    md = sa.MetaData()
    return [
        sa.Table(name, md, sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64)),
                 info={**TENANT_SCOPED, **TEAM_OWNED})
        for name in (DISCOVERIES, OPERATIONS)
    ]  # fmt: skip


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    op.create_table(
        DISCOVERIES,
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("person", sa.String(128), nullable=False),
        sa.Column("module_id", sa.String(64), nullable=True),
        sa.Column("meta", sa.JSON, nullable=False),
        sa.Column("operation_total", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="tool_discoveries_pkey"),
    )
    op.create_index("ix_tool_discoveries_expires", DISCOVERIES, ["tenant_id", "team_id", "expires_at"])
    op.create_table(
        OPERATIONS,
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("discovery_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("access", sa.String(16), nullable=False),
        sa.Column("method", sa.String(8), nullable=True),
        sa.Column("path", sa.Text, nullable=True),
        sa.Column("op_group", sa.String(200), nullable=False),
        sa.Column("input", sa.JSON, nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "discovery_id", "position", name="tool_discovery_operations_pkey"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "discovery_id"],
            [f"{DISCOVERIES}.tenant_id", f"{DISCOVERIES}.id"],
            name="tool_discovery_operations_discovery_fkey",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_tool_discovery_operations_name", OPERATIONS, ["tenant_id", "discovery_id", "name"])
    op.create_index(
        "ix_tool_discovery_operations_access", OPERATIONS, ["tenant_id", "team_id", "access", "discovery_id"]
    )
    op.create_index(
        "ix_tool_discovery_operations_group", OPERATIONS, ["tenant_id", "team_id", "op_group", "discovery_id"]
    )
    dialect = op.get_context().dialect.name
    tables = _marked()
    if dialect == "postgresql":
        for name in (DISCOVERIES, OPERATIONS):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {ROLE}")
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    else:
        return
    for table in tables:
        for statement in isolation_ddl(table, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for table in _marked():
            for statement in isolation_drop_ddl(table, dialect):
                op.execute(statement)
    if dialect == "postgresql":
        for name in (OPERATIONS, DISCOVERIES):
            op.execute(f"REVOKE ALL ON {name} FROM {ROLE}")
    for name in (
        "ix_tool_discovery_operations_group",
        "ix_tool_discovery_operations_access",
        "ix_tool_discovery_operations_name",
    ):
        op.drop_index(name, table_name=OPERATIONS)  # fmt: skip
    op.drop_table(OPERATIONS)
    op.drop_index("ix_tool_discoveries_expires", table_name=DISCOVERIES)
    op.drop_table(DISCOVERIES)
