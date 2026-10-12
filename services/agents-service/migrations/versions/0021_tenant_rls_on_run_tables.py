"""tenant_id and team_id on the run tables, with tenant row-level security

Revision ID: 0021_tenant_rls_run_tables
Revises: 0020_model_call_records

graph_threads, graph_runs, thread_events, review_decisions and review_approvals gain tenant_id (existing rows are the
dev tenant, "local") and team_id (copied from the thread where the table had none). On PostgreSQL each table gets
the same policy as the checkpoint tables (0004): a row is visible and writable only while `app.tenant_id` names its
tenant, under `ops_runtime_tenant`. `ops_runtime_system` bypasses RLS and is used only by the sweeper, timer poller
and inbox drain to read which tenant a claimed thread belongs to. A thread's external key is unique per tenant.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_tenant_rls_run_tables"
down_revision = "0020_model_call_records"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLES = ("graph_threads", "graph_runs", "thread_events", "review_decisions", "review_approvals")
# Tables that had no team_id: filled from their thread.
TEAMLESS = ("graph_runs", "review_decisions", "review_approvals")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("tenant_id", sa.String(64), nullable=False, server_default="local"))
            if table in TEAMLESS:
                b.add_column(sa.Column("team_id", sa.String(64)))
    for table in TEAMLESS:
        op.execute(
            f"UPDATE {table} SET team_id = (SELECT t.team_id FROM graph_threads t WHERE t.id = {table}.thread_id)"
        )
    for table in TABLES:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    with op.batch_alter_table("graph_threads") as b:
        b.drop_constraint("uq_graph_threads_external_key", type_="unique")
        b.create_unique_constraint("uq_graph_threads_tenant_external_key", ["tenant_id", "external_key"])

    if op.get_bind().dialect.name != "postgresql":
        return
    # Roles are cluster-wide, so another database on the same server may already have created them.
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(
        f"DO $$ BEGIN CREATE ROLE {SYSTEM_ROLE} NOLOGIN BYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {TENANT_ROLE}")
        op.execute(f"GRANT SELECT ON {table} TO {SYSTEM_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE makes the policy apply to the table owner too; only superusers and BYPASSRLS roles skip it.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # An unset app.tenant_id reads as NULL, which matches no row: a statement without a tenant sees nothing.
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    op.execute(f"GRANT USAGE ON SEQUENCE thread_events_position_seq TO {TENANT_ROLE}")
    # A run's writes check its lease fence (FOR SHARE) inside the tenant transaction.
    op.execute(f"GRANT SELECT, UPDATE ON thread_leases TO {TENANT_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
            op.execute(f"REVOKE ALL ON {table} FROM {TENANT_ROLE}")
            op.execute(f"REVOKE ALL ON {table} FROM {SYSTEM_ROLE}")
        op.execute(f"REVOKE USAGE ON SEQUENCE thread_events_position_seq FROM {TENANT_ROLE}")
        op.execute(f"REVOKE ALL ON thread_leases FROM {TENANT_ROLE}")
    with op.batch_alter_table("graph_threads") as b:
        b.drop_constraint("uq_graph_threads_tenant_external_key", type_="unique")
        b.create_unique_constraint("uq_graph_threads_external_key", ["external_key"])
    for table in TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table)
        with op.batch_alter_table(table) as b:
            b.drop_column("tenant_id")
            if table in TEAMLESS:
                b.drop_column("team_id")
