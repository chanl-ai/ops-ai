"""engine_runs, engine_steps and engine_work: the workflow runner's runs, step journal and work queue

Revision ID: 0024_engine_runs_steps_work
Revises: 0023_engine_definitions

Tenant rows with forced row-level security, as 0021 set for the run tables. A worker claims engine_work before it
knows the tenant, so ops_runtime_system (BYPASSRLS) may read and update that table, and only that one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_engine_runs_steps_work"
down_revision = "0023_engine_definitions"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLES = ("engine_runs", "engine_steps", "engine_work")


def upgrade() -> None:
    op.create_table(
        "engine_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("workflow_id", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("run_key", sa.String(200), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input", sa.JSON),
        sa.Column("outcome", sa.String(64)),
        sa.Column("output", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("waiting", sa.JSON),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("finished_at", sa.String(32)),
        sa.UniqueConstraint("tenant_id", "workflow_id", "run_key", name="uq_engine_runs_key"),
    )
    op.create_table(
        "engine_steps",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("node_id", sa.String(80), primary_key=True),
        sa.Column("iteration", sa.Integer, primary_key=True),
        sa.Column("attempt", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("effects", sa.String(8), nullable=False),
        sa.Column("key", sa.String(240), nullable=False),
        sa.Column("input", sa.JSON),
        sa.Column("port", sa.String(80)),
        sa.Column("output", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.String(32), nullable=False),
        sa.Column("finished_at", sa.String(32)),
    )
    op.create_table(
        "engine_work",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("run_id", sa.String(64), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON),
        sa.Column("dedupe_key", sa.String(240), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("build", sa.String(32), nullable=False),
        sa.Column("available_at", sa.Float(), nullable=False),
        sa.Column("claimed_by", sa.String(120)),
        sa.Column("lease_expires_at", sa.Float()),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_engine_work_dedupe"),
    )
    # The claim's scan: due rows of one build, oldest first.
    op.create_index("ix_engine_work_due", "engine_work", ["status", "build", "available_at"])
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {TENANT_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    op.execute(f"GRANT USAGE ON SEQUENCE engine_work_id_seq TO {TENANT_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON engine_work TO {SYSTEM_ROLE}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
