"""cases and case_events: a team's long-lived issues and their timelines (c-128)

Revision ID: 0053_cases
Revises: 0052_drop_engine_settings

Tenant RLS as on poll_cursors (0045). A case's producer key is unique per tenant and team, so a producer's retry finds
the case it opened. Timeline events are only ever added.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0053_cases"
down_revision = "0052_drop_engine_settings"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("producer_key", sa.String(200)),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("customer_id", sa.String(200)),
        sa.Column("customer_name", sa.String(300)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("assignee", sa.String(320)),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("response_due_at", sa.String(32), nullable=False),
        sa.Column("resolution_due_at", sa.String(32), nullable=False),
        sa.Column("responded_at", sa.String(32)),
        sa.Column("paused_since", sa.String(32)),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("tenant_id", "team_id", "producer_key", name="uq_cases_producer_key"),
    )
    op.create_index("ix_cases_team_due", "cases", ["tenant_id", "team_id", "resolution_due_at"])
    op.create_table(
        "case_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("case_id", sa.String(64), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("ref", sa.String(200)),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("by", sa.String(320), nullable=False),
        sa.Column("at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON cases TO {TENANT_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON case_events TO {TENANT_ROLE}")
    for table in ("cases", "case_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("cases", "case_events"):
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
    op.drop_table("case_events")
    op.drop_index("ix_cases_team_due", table_name="cases")
    op.drop_table("cases")
