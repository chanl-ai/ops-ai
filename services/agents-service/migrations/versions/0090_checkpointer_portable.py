"""The checkpointer's tables on SQL Server, and a checkpoint's run as a column (c-549)

Revision ID: 0090_checkpointer_portable
Revises: 0089_trigger_event_item_update

The checkpointer's tables were raw PostgreSQL DDL (0004, 0008) with no metadata, so the SQL Server baseline (0070) has
none of them and an install upgraded from it had nowhere to save a chat's state. On SQL Server this creates the three
tables as packages/ops_checkpointer/tables.py defines them, with a team security policy each. On PostgreSQL, where
they exist, they are brought to that definition: key columns bounded (SQL Server refuses VARCHAR(max) in a key), the
metadata column JSON without its GIN index (other keys are filtered after reading, the same on both databases), and
run_id, the one key a query filters on, a column with a plain index in place of 0071's expression index. Their tenant
policies become team policies, as on every table with a team column; the saver sets its team in each transaction.
Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.dialect import db_now
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0090_checkpointer_portable"
down_revision = "0089_trigger_event_item_update"
branch_labels = None
depends_on = None

CHAIN = "agents"
SYSTEM_ROLE = "ops_runtime_system"
TABLES = ("ops_checkpoints", "ops_checkpoint_writes", "ops_checkpoint_fences")
# Each table's key columns and their bound: SQL Server refuses VARCHAR(max) in a key, so both databases bound them.
KEYS: dict[str, dict[str, int]] = {
    "ops_checkpoints": {"tenant_id": 64, "team_id": 64, "thread_id": 64, "checkpoint_ns": 255, "checkpoint_id": 64},
    "ops_checkpoint_writes": {
        "tenant_id": 64,
        "team_id": 64,
        "thread_id": 64,
        "checkpoint_ns": 255,
        "checkpoint_id": 64,
        "task_id": 64,
    },
    "ops_checkpoint_fences": {"tenant_id": 64, "team_id": 64, "thread_id": 64},
}


def _marked(name: str) -> sa.Table:
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _keys() -> list[sa.Column[Any]]:
    return [
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
    ]


def _sql_server_tables() -> None:
    op.create_table(
        "ops_checkpoints",
        *_keys(),
        sa.Column("checkpoint_ns", sa.String(255), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text()),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("checkpoint", sa.LargeBinary(), nullable=False),
        sa.Column("metadata_type", sa.Text(), nullable=False),
        sa.Column("metadata_blob", sa.LargeBinary(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("run_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
        sa.PrimaryKeyConstraint("tenant_id", "team_id", "thread_id", "checkpoint_ns", "checkpoint_id"),
    )
    op.create_index("ix_ops_checkpoints_run", "ops_checkpoints", ["tenant_id", "team_id", "run_id"])
    op.create_table(
        "ops_checkpoint_writes",
        *_keys(),
        sa.Column("checkpoint_ns", sa.String(255), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.Column("task_path", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint(
            "tenant_id", "team_id", "thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"
        ),
    )
    op.create_table(
        "ops_checkpoint_fences",
        *_keys(),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "team_id", "thread_id"),
    )
    marked = [_marked(t) for t in TABLES]
    for statement in mssql_predicates_ddl(CHAIN, marked, column_type=_column_type, system_user=SYSTEM_ROLE):
        op.execute(statement)
    for table in marked:
        for statement in isolation_ddl(table, "mssql", kind="team", chain=CHAIN):
            op.execute(statement)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "mssql":
        _sql_server_tables()
    elif dialect == "postgresql":
        # The migrating role may own the table; FORCE row-level security would otherwise hide every row from it.
        op.execute("SET LOCAL row_security = off")
        op.execute("DROP INDEX IF EXISTS ix_ops_checkpoints_run")
        op.execute("DROP INDEX IF EXISTS ix_ops_checkpoints_metadata")
        for t in TABLES:
            # A column a policy reads cannot change type, so the tenant policy goes first; the team policy follows.
            op.execute(f"DROP POLICY IF EXISTS {t}_tenant ON {t}")
            for name, length in KEYS[t].items():
                op.alter_column(t, name, type_=sa.String(length), existing_type=sa.Text(), existing_nullable=False)
        op.alter_column("ops_checkpoints", "metadata", server_default=None)
        op.alter_column("ops_checkpoints", "metadata", type_=sa.JSON())
        op.alter_column("ops_checkpoints", "metadata", server_default="{}")
        op.add_column("ops_checkpoints", sa.Column("run_id", sa.String(64)))
        op.execute("UPDATE ops_checkpoints SET run_id = json_extract_path_text(metadata, 'run_id')")
        op.create_index("ix_ops_checkpoints_run", "ops_checkpoints", ["tenant_id", "team_id", "run_id"])
        for t in TABLES:
            for statement in isolation_ddl(_marked(t), "postgresql", kind="team"):
                op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "mssql":
        for t in TABLES:
            policy = f"ops_security.{t}_isolation"
            op.execute(f"IF OBJECT_ID(N'{policy}', N'SP') IS NOT NULL DROP SECURITY POLICY {policy}")
            op.drop_table(t)
    elif dialect == "postgresql":
        # Back to 0089's text keys and tenant policies. The metadata column stays JSON: 0089's checkpointer reads it
        # through a cast, and its GIN index is not rebuilt.
        op.drop_index("ix_ops_checkpoints_run", table_name="ops_checkpoints")
        op.drop_column("ops_checkpoints", "run_id")
        for t in TABLES:
            op.execute(f"DROP POLICY IF EXISTS {t}_isolation ON {t}")
            for name in KEYS[t]:
                op.alter_column(t, name, type_=sa.Text(), existing_nullable=False)
            for statement in isolation_ddl(_marked(t), "postgresql", kind="tenant"):
                op.execute(statement)
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ops_checkpoints_run ON ops_checkpoints "
            "(tenant_id, team_id, json_extract_path_text(metadata, 'run_id'))"
        )
