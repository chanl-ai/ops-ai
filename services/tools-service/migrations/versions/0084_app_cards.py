"""app_cards: each team's Apps cards as rows, so the list pages, searches and sorts in SQL

GET /v1/apps built every card in Python from the installed plugins' manifests, the built-in app list, the team's
plugin bindings and its accounts, then sorted them by name. app_cards holds one row per card a team has (its id, kind,
name and category), held to its tenant and team by the generated policy for ops_tools_tenant on both databases.
team_defaults.cards_stamp records the install stamp a team's rows were built for; a write that changes a team's cards
clears it, and the next list rebuilds the rows.

No backfill: the manifests live in the running service, not the database, so every team's stamp starts empty and its
first list after this release builds its rows. Downgrade drops the policy, the table and the column.

Revision ID: tools_0084_app_cards
Revises: tools_0083_system_reads_columns
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "tools_0084_app_cards"
down_revision = "tools_0083_system_reads_columns"
branch_labels = None
depends_on = None

CHAIN = "tools"
ROLE = "ops_tools_tenant"
SYSTEM_ROLE = "ops_tools_system"
TABLE = "app_cards"


def _marked() -> sa.Table:
    columns = [sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64))]
    return sa.Table(TABLE, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED})


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    op.add_column("team_defaults", sa.Column("cards_stamp", sa.String(64), nullable=True))
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("id", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(120), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "team_id", "id", name="app_cards_pkey"),
    )
    op.create_index("ix_app_cards_name", TABLE, ["tenant_id", "team_id", "name"])
    dialect = op.get_context().dialect.name
    table = _marked()
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {ROLE}")
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [table], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    else:
        return
    for statement in isolation_ddl(table, dialect, chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked(), dialect):
            op.execute(statement)
    if dialect == "postgresql":
        op.execute(f"REVOKE ALL ON {TABLE} FROM {ROLE}")
    op.drop_index("ix_app_cards_name", table_name=TABLE)
    op.drop_table(TABLE)
    op.drop_column("team_defaults", "cards_stamp")
