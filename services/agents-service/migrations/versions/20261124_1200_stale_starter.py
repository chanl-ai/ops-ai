"""Unfinished runs stop approving their writes as their starter's

Revision ID: 20261124_1200_stale_starter
Revises: 20261124_0257_skill_owner_ids

`engine_runs.started_by_approver` was read from the starter's roles and the retired requesterMayDecide policy when the
run started, so a run waiting across this release would approve its write as the starter's on a yes nobody can
untick. Every run not yet succeeded, failed or cancelled takes false: its review step waits for a person, and whether
the starter may decide their own write is read live where the write is sent. Finished runs keep their record. Rows are
rewritten as the table's owner with its row policy set aside for the statement (`backfill_ddl`). A second run changes
nothing. The downgrade restores nothing: which runs held a yes is not kept. The column is dropped in 1.3.0.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl

revision = "20261124_1200_stale_starter"
down_revision = "20261124_0257_skill_owner_ids"
branch_labels = None
depends_on = None

CHAIN = "agents"
# ops_engine.store.runs.TERMINAL as of this revision.
FINISHED = ("succeeded", "failed", "cancelled")


def _runs() -> sa.Table:
    """engine_runs as far as this revision reads and its policy needs."""
    return sa.Table(
        "engine_runs",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        sa.Column("status", sa.String(16)),
        sa.Column("started_by_approver", sa.Boolean),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def upgrade() -> None:
    runs = _runs()
    before, after = backfill_ddl([runs], op.get_bind().dialect.name, chain=CHAIN, kind="team")
    for statement in before:
        op.execute(statement)
    op.execute(
        runs.update()
        .where(runs.c.started_by_approver == sa.true(), runs.c.status.not_in(FINISHED))
        .values(started_by_approver=sa.false())
    )
    for statement in after:
        op.execute(statement)


def downgrade() -> None:
    """Nothing to restore: which runs held a yes is not kept."""
