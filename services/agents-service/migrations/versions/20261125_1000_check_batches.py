"""run_batches and run_batch_rows hold a watched folder's check as well as a spreadsheet

Revision ID: 20261125_1000_check_batches
Revises: 20261124_0257_skill_owner_ids

A Files changed trigger turns one check of a watched folder into one batch: `origin` says which kind a batch is
(`upload` for every batch before this), a check names its watch and check time and has no file, so `file_id` becomes
nullable and `file_name` holds the check's label. A row gains its workflow and an `item_key` with a unique index per
workflow, so one file version is one row however many checks read it; spreadsheet rows are backfilled as
`<batch>:<row>`, which both databases build by string concatenation. `failure_code` and `reason` say why a row that
never ran (removed at the source, too large) did not. `ix_run_batches_created` serves the batch list's sort. The
backfill runs as the tables' owner with the row policies set aside for it (`backfill_ddl`). The downgrade deletes
check batches, which the earlier shape cannot hold.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl, mssql_drop_default_ddl

revision = "20261125_1000_check_batches"
down_revision = "20261124_0257_skill_owner_ids"
branch_labels = None
depends_on = None

CHAIN = "agents"


def _policed() -> list[sa.Table]:
    """The two tables as far as their policies need, as of this revision."""
    cols = lambda: [sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64))]  # noqa: E731
    return [
        sa.Table(name, sa.MetaData(), *cols(), info={**TENANT_SCOPED, **TEAM_OWNED})
        for name in ("run_batches", "run_batch_rows")
    ]


def _aside(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    with op.batch_alter_table("run_batches") as b:
        b.add_column(sa.Column("origin", sa.String(8), nullable=False, server_default="upload"))
        b.add_column(sa.Column("watch_id", sa.String(64)))
        b.add_column(sa.Column("checked_at", sa.String(32)))
        b.alter_column("file_id", existing_type=sa.String(64), nullable=True)
    with op.batch_alter_table("run_batch_rows") as b:
        b.add_column(sa.Column("workflow_id", sa.String(200)))
        b.add_column(sa.Column("item_key", sa.String(96)))
        b.add_column(sa.Column("failure_code", sa.String(32)))
        b.add_column(sa.Column("reason", sa.String(500)))
    before, after = backfill_ddl(_policed(), dialect, chain=CHAIN, kind="team")
    _aside(before)
    joined = "batch_id + ':' + CAST([row] AS VARCHAR(12))" if dialect == "mssql" else "batch_id || ':' || \"row\""
    op.execute(
        "UPDATE run_batch_rows SET workflow_id = (SELECT b.workflow_id FROM run_batches b"
        " WHERE b.tenant_id = run_batch_rows.tenant_id AND b.id = run_batch_rows.batch_id),"
        f" item_key = {joined}"
    )
    _aside(after)
    with op.batch_alter_table("run_batch_rows") as b:
        b.alter_column("workflow_id", existing_type=sa.String(200), nullable=False)
        b.alter_column("item_key", existing_type=sa.String(96), nullable=False)
    op.create_index("ux_run_batch_rows_item", "run_batch_rows", ["tenant_id", "workflow_id", "item_key"], unique=True)
    op.create_index("ix_run_batches_created", "run_batches", ["tenant_id", "team_id", "created_at"])


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    before, after = backfill_ddl(_policed(), dialect, chain=CHAIN, kind="team")
    _aside(before)
    op.execute(
        "DELETE FROM run_batch_rows WHERE EXISTS (SELECT 1 FROM run_batches b WHERE b.tenant_id ="
        " run_batch_rows.tenant_id AND b.id = run_batch_rows.batch_id AND b.origin = 'check')"
    )
    op.execute("DELETE FROM run_batches WHERE origin = 'check'")
    _aside(after)
    op.drop_index("ix_run_batches_created", table_name="run_batches")
    op.drop_index("ux_run_batch_rows_item", table_name="run_batch_rows")
    with op.batch_alter_table("run_batch_rows") as b:
        for name in ("reason", "failure_code", "item_key", "workflow_id"):
            b.drop_column(name)
    if dialect == "mssql":
        # SQL Server refuses to drop a column while its default constraint is bound to it.
        op.execute(mssql_drop_default_ddl("run_batches", "origin"))
    with op.batch_alter_table("run_batches") as b:
        b.alter_column("file_id", existing_type=sa.String(64), nullable=False)
        for name in ("checked_at", "watch_id", "origin"):
            b.drop_column(name)
