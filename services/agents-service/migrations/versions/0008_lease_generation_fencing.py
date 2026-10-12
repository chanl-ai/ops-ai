"""lease generation and fencing tables for the checkpointer and the gateway (E2b)

Revision ID: 0008_lease_generation
Revises: 0007_timers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_lease_generation"
down_revision = "0007_timers"
branch_labels = None
depends_on = None

ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    # The Runtime's lease generation goes up on every acquire or takeover and is never reset: released leases stay
    # as rows (released_at set) instead of being deleted.
    op.add_column("thread_leases", sa.Column("generation", sa.BigInteger(), nullable=False, server_default="1"))
    op.add_column("thread_leases", sa.Column("released_at", sa.Float(), nullable=True))
    # Each writer keeps its own fence: the highest generation it has seen per thread. A write below it is refused.
    # Neither reads the Runtime's lease table; the generation arrives with the write.
    op.execute(
        """
        CREATE TABLE ops_checkpoint_fences (
            tenant_id text NOT NULL,
            team_id text NOT NULL,
            thread_id text NOT NULL,
            generation bigint NOT NULL,
            PRIMARY KEY (tenant_id, team_id, thread_id)
        )
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ops_checkpoint_fences TO {ROLE}")
    op.execute("ALTER TABLE ops_checkpoint_fences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ops_checkpoint_fences FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY ops_checkpoint_fences_tenant ON ops_checkpoint_fences "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
    op.create_table(
        "gateway_fences",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("gateway_fences")
    op.execute("DROP TABLE ops_checkpoint_fences")
    op.drop_column("thread_leases", "released_at")
    op.drop_column("thread_leases", "generation")
