"""engine_work: the team, priority, concurrency key and rate-limit key a fair claim reads

Revision ID: 0124_engine_work_fair_claim
Revises: 0123_run_failure_record

The claim took the oldest due row of any tenant, so one team's long runs could hold every worker. A claim now skips a
concurrency key (the team when none is set) whose claimed rows are at its cap and takes keys in turn
(ops_engine/store/work.py). `rate_key` names a connector account or model key whose own limit comes later.

engine_work is the live queue: every worker claims from it several times a second. The four columns are nullable with
no default, so adding them rewrites no rows on PostgreSQL or SQL Server. The open rows (queued or claimed, a few per
running run; done rows are left) are then given their run's team and priority 0, so a row queued before this counts
under its own team's cap rather than one key shared by every team. ix_engine_work_claim holds the claim's order, so a
claim reads rows in it instead of sorting every due row. Adding a column still takes the table's exclusive lock, which
waits behind an open claim and holds every later claim behind it, so the step gives up after LOCK_TIMEOUT rather than
stalling the queue, and is run again.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0124_engine_work_fair_claim"
down_revision = "0123_run_failure_record"
branch_labels = None
depends_on = None

LOCK_TIMEOUT_MS = 3000
COLUMNS = (
    sa.Column("team_id", sa.String(64), nullable=True),
    sa.Column("priority", sa.Integer(), nullable=True),
    sa.Column("concurrency_key", sa.String(240), nullable=True),
    sa.Column("rate_key", sa.String(240), nullable=True),
)


def _bounded_wait() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MS}")
    elif op.get_bind().dialect.name == "mssql":
        op.execute(f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}")


def upgrade() -> None:
    _bounded_wait()
    for column in COLUMNS:
        op.add_column("engine_work", column.copy())
    work = sa.table(
        "engine_work",
        sa.column("tenant_id"),
        sa.column("run_id"),
        sa.column("status"),
        sa.column("team_id"),
        sa.column("priority"),
    )
    runs = sa.table("engine_runs", sa.column("tenant_id"), sa.column("id"), sa.column("team_id"))
    team = (
        sa.select(runs.c.team_id)
        .where(runs.c.tenant_id == work.c.tenant_id, runs.c.id == work.c.run_id)
        .scalar_subquery()
    )
    op.execute(work.update().where(work.c.status.in_(("queued", "claimed"))).values(team_id=team, priority=0))
    op.create_index(
        "ix_engine_work_claim", "engine_work", ["status", "build", sa.text("priority DESC"), "id"], unique=False
    )


def downgrade() -> None:
    _bounded_wait()
    op.drop_index("ix_engine_work_claim", table_name="engine_work")
    for column in reversed(COLUMNS):
        op.drop_column("engine_work", column.name)
