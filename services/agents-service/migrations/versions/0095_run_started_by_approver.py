"""engine_runs.started_by_approver: whether the person who started a run may approve its writes themselves

Roles decide approvals: a person holding reviews.decide in the run's team, while the
requesterMayDecide policy lets an asker decide, is not asked to approve their own run's write. A run's steps run later
in the worker, where no principal is at hand, so the answer from the starter's roles is recorded when the run starts.
Existing runs take false: their writes keep waiting for a person as they did.

Revision ID: 0095_run_started_by_approver
Revises: 0094_template_copies_digest
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import mssql_drop_default_ddl

revision = "0095_run_started_by_approver"
down_revision = "0094_template_copies_digest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "engine_runs", sa.Column("started_by_approver", sa.Boolean, nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    # SQL Server refuses to drop a column that holds a default; the helper drops one only if it is there.
    if op.get_context().dialect.name == "mssql":
        op.execute(mssql_drop_default_ddl("engine_runs", "started_by_approver"))
    op.drop_column("engine_runs", "started_by_approver")
