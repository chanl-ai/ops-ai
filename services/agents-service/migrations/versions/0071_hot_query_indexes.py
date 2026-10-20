"""Indexes that lead with the filters of the hot workflow and agent queries (c-280)

The worker's claim takes either queued work that is due or claimed work whose lease lapsed; only the first branch had
an index, so every poll scanned the queue for lapsed leases. A service event's listeners and the mailbox listener read
live versions only, from a table that keeps every version of every workflow. Deleting a run's checkpoints matched
the run id inside each checkpoint's metadata row by row. A team's thread list and its event poll
led with the team id alone, which is the same across tenants. The runs list filtered by one workflow had no index on
it. Each is created only when missing: a table too large to lock is indexed CONCURRENTLY by hand before this runs
(docs/runbooks/deploy.md).

Revision ID: 0071_hot_query_indexes
Revises: 0070_engine_definitions_archived
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0071_hot_query_indexes"
down_revision = "0070_engine_definitions_archived"
branch_labels = None
depends_on = None

LIVE = sa.text("stage = 'live'")


def upgrade() -> None:
    op.create_index("ix_engine_work_lease", "engine_work", ["status", "build", "lease_expires_at"], if_not_exists=True)
    op.create_index(
        "ix_engine_definitions_live",
        "engine_definitions",
        ["tenant_id", "workflow_id"],
        postgresql_where=LIVE,
        mssql_where=LIVE,
        if_not_exists=True,
    )
    op.create_index(
        "ix_graph_threads_team_updated", "graph_threads", ["tenant_id", "team_id", "updated_at"], if_not_exists=True
    )
    op.create_index(
        "ix_thread_events_tenant_team_position",
        "thread_events",
        ["tenant_id", "team_id", "position"],
        if_not_exists=True,
    )
    op.drop_index("ix_thread_events_team_position", table_name="thread_events")
    op.create_index(
        "ix_engine_runs_workflow_created", "engine_runs", ["tenant_id", "workflow_id", "created_at"], if_not_exists=True
    )

    # ops_checkpoints is the PostgreSQL checkpointer's own table (raw asyncpg, migration 0004) until its SQL Server
    # rewrite: adelete_for_runs matches metadata->>'run_id' within a tenant and team.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ops_checkpoints_run ON ops_checkpoints "
        "(tenant_id, team_id, (metadata->>'run_id'))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ops_checkpoints_run")
    op.drop_index("ix_engine_runs_workflow_created", table_name="engine_runs")
    op.create_index("ix_thread_events_team_position", "thread_events", ["team_id", "position"])
    op.drop_index("ix_thread_events_tenant_team_position", table_name="thread_events")
    op.drop_index("ix_graph_threads_team_updated", table_name="graph_threads")
    op.drop_index("ix_engine_definitions_live", table_name="engine_definitions")
    op.drop_index("ix_engine_work_lease", table_name="engine_work")
