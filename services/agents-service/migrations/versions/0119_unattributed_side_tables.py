"""The side tables of agents 0104 on a database that ran 0104 before it made them

Revision ID: 0119_unattributed_side_tables
Revises: 0118_channel_list_columns

agents 0104 moves spend no tenant can be named for into `thread_budgets_unattributed` and
`model_call_records_unattributed`. An earlier form of 0104 deleted those rows and made no side tables, so a database
that ran it lacks both tables the store metadata and the golden DDL define, and drift and the upgrade proof name them.
This step makes each one when it is missing, with 0104's columns and marking (system: granted to no tenant role); on a
database 0104 already gave them it does nothing. It can run again. Offline SQL cannot look, so PostgreSQL's script says
IF NOT EXISTS and SQL Server's creates each table only when OBJECT_ID finds none.

The down path leaves the tables: from here on they are 0104's, and 0104's own down path moves their rows back before
it drops them, so it makes any that are missing, as the upgrade does. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql
from sqlalchemy.schema import CreateTable

from ops_store.dialect import db_now
from ops_store.schema import offline_dialect_opts, system

revision = "0119_unattributed_side_tables"
down_revision = "0118_channel_list_columns"
branch_labels = None
depends_on = None

# As agents 0104 makes them; a migration does not import another revision.
SIDE = {"thread_budgets": "thread_budgets_unattributed", "model_call_records": "model_call_records_unattributed"}
UNATTRIBUTED = "unattributed rows kept from before tenancy: a thread gone and no other row naming its tenant (0104)"


def _side_columns(name: str) -> list[sa.Column[Any]]:
    """0104's columns for the side table of `name`, as of that revision."""
    if name == "thread_budgets":
        kept = [
            sa.Column("thread_id", sa.String(64), primary_key=True),
            sa.Column("max_calls", sa.Integer()),
            sa.Column("max_tokens", sa.BigInteger()),
            sa.Column("max_cost_micros", sa.BigInteger()),
            sa.Column("updated_at", sa.String(40), nullable=False),
        ]
    else:
        kept = [
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("run_id", sa.String(64)),
            sa.Column("step", sa.String(120), nullable=False),
            sa.Column("task", sa.String(200)),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("model_alias", sa.String(120), nullable=False),
            sa.Column("calls", sa.Integer(), nullable=False),
            sa.Column("input_tokens", sa.BigInteger(), nullable=False),
            sa.Column("output_tokens", sa.BigInteger(), nullable=False),
            sa.Column("cost_micros", sa.BigInteger(), nullable=False),
            sa.Column("latency_ms", sa.Integer()),
            sa.Column("request_hash", sa.String(64)),
            sa.Column("response", sa.JSON()),
            sa.Column("created_at", sa.String(40), nullable=False),
        ]
    return [*kept, sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now())]


def _ensure_sides() -> None:
    """Makes each side table that is missing; leaves one that is there."""
    context = op.get_context()
    dialect = context.dialect.name
    offline = context.as_sql
    for name, side in SIDE.items():
        columns = _side_columns(name)
        # Named as the store metadata and the golden DDL name it; SQL Server would generate a name otherwise.
        key = sa.PrimaryKeyConstraint(*(c.name for c in columns if c.primary_key), name=f"{side}_pkey")
        for c in columns:
            c.primary_key = False
        if not offline:
            if sa.inspect(op.get_bind()).has_table(side):
                continue
            op.create_table(side, *columns, key, info=system(UNATTRIBUTED))
        elif dialect == "mssql":
            table = sa.Table(side, sa.MetaData(), *columns, key)
            ddl = str(CreateTable(table).compile(dialect=mssql.dialect(**offline_dialect_opts("mssql"))))
            quoted = ddl.strip().replace("'", "''")
            op.execute(f"IF OBJECT_ID(N'dbo.{side}', N'U') IS NULL EXEC (N'{quoted}')")
        else:
            op.create_table(side, *columns, key, info=system(UNATTRIBUTED), if_not_exists=True)


def upgrade() -> None:
    _ensure_sides()


def downgrade() -> None:
    # 0104's down path reads both tables; on a database that ran its earlier form they exist only from this step.
    _ensure_sides()
