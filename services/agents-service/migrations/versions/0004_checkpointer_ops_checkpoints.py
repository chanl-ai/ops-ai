"""ops checkpointer tables with tenant row-level security

Revision ID: 0004_checkpointer
Revises: 0003_graph_versions
"""

from __future__ import annotations

from alembic import op

revision = "0004_checkpointer"
down_revision = "0003_graph_versions"
branch_labels = None
depends_on = None

ROLE = "ops_runtime_tenant"
TABLES = ("ops_checkpoints", "ops_checkpoint_writes")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ops_checkpoints (
            tenant_id text NOT NULL,
            team_id text NOT NULL,
            thread_id text NOT NULL,
            checkpoint_ns text NOT NULL DEFAULT '',
            checkpoint_id text NOT NULL,
            parent_checkpoint_id text,
            type text NOT NULL,
            checkpoint bytea NOT NULL,
            metadata_type text NOT NULL,
            metadata_blob bytea NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ops_checkpoint_writes (
            tenant_id text NOT NULL,
            team_id text NOT NULL,
            thread_id text NOT NULL,
            checkpoint_ns text NOT NULL DEFAULT '',
            checkpoint_id text NOT NULL,
            task_id text NOT NULL,
            idx integer NOT NULL,
            channel text NOT NULL,
            type text NOT NULL,
            blob bytea NOT NULL,
            task_path text NOT NULL DEFAULT '',
            PRIMARY KEY (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        )
        """
    )
    op.execute("CREATE INDEX ix_ops_checkpoints_metadata ON ops_checkpoints USING gin (metadata)")
    # Roles are cluster-wide, so another database on the same server may already have created it.
    op.execute(f"DO $$ BEGIN CREATE ROLE {ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE makes the policy apply to the table owner too; only superusers still bypass it.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # An unset app.tenant_id reads as NULL, which matches no row: a statement without a tenant sees nothing.
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
