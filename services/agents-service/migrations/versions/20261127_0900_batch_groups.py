"""run_batches carries its group, and batch_waiting_files holds the files of a group that is not ready

Revision ID: 20261127_0900_batch_groups
Revises: 20261125_1000_check_batches

A Files changed trigger with Group by makes one batch per group (a subfolder, a date, a client), named by it, and a
later check that adds a file to a group adds rows to that group's batch. `group_key` (a digest of the group's name)
and `part` name the batch, unique per workflow; a group past 500 rows opens part 2. Every batch before this is its own
group: `group_key` is backfilled with the batch id, `part` with 1. `batch_waiting_files` holds the files of a group
whose Ready when has not passed yet, one row per file version, tenant scoped and team owned as the batches are. The
downgrade drops the table, and the waiting files with it; batches keep their rows.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    backfill_ddl,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_drop_default_ddl,
    mssql_predicates_ddl,
)

revision = "20261127_0900_batch_groups"
down_revision = "20261125_1000_check_batches"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
WAITING = "batch_waiting_files"


def _marked(name: str) -> sa.Table:
    """A table as far as its policy needs, as of this revision."""
    cols = [sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64))]
    return sa.Table(name, sa.MetaData(), *cols, info={**TENANT_SCOPED, **TEAM_OWNED})


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    with op.batch_alter_table("run_batches") as b:
        b.add_column(sa.Column("group_key", sa.String(96)))
        b.add_column(sa.Column("group_name", sa.String(300)))
        b.add_column(sa.Column("group_parts", sa.JSON))
        b.add_column(sa.Column("part", sa.Integer, nullable=False, server_default="1"))
    before, after = backfill_ddl([_marked("run_batches")], dialect, chain=CHAIN, kind="team")
    for statement in before:
        op.execute(statement)
    op.execute("UPDATE run_batches SET group_key = id")
    for statement in after:
        op.execute(statement)
    with op.batch_alter_table("run_batches") as b:
        b.alter_column("group_key", existing_type=sa.String(96), nullable=False)
    op.create_index(
        "ux_run_batches_group", "run_batches", ["tenant_id", "workflow_id", "group_key", "part"], unique=True
    )
    op.create_table(
        WAITING,
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(200), primary_key=True),
        sa.Column("item_key", sa.String(96), primary_key=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("group_key", sa.String(96), nullable=False),
        sa.Column("group_name", sa.String(300), nullable=False),
        sa.Column("input", sa.JSON, nullable=False),
        sa.Column("held_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_batch_waiting_group", WAITING, ["tenant_id", "workflow_id", "group_key"])
    if dialect not in ("postgresql", "mssql"):
        return
    table = _marked(WAITING)
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [table], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    else:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {WAITING} TO {TENANT_ROLE}")
    for statement in isolation_ddl(table, dialect, kind="team", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked(WAITING), dialect):
            op.execute(statement)
    op.drop_index("ix_batch_waiting_group", table_name=WAITING)
    op.drop_table(WAITING)
    op.drop_index("ux_run_batches_group", table_name="run_batches")
    if dialect == "mssql":
        # SQL Server refuses to drop a column while its default constraint is bound to it.
        op.execute(mssql_drop_default_ddl("run_batches", "part"))
    with op.batch_alter_table("run_batches") as b:
        for name in ("part", "group_parts", "group_name", "group_key"):
            b.drop_column(name)
