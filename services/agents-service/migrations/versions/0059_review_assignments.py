"""review_assignments: who a Human Task is assigned to, one row per assignment (c-074)

Revision ID: 0059_review_assignments
Revises: 0058_widget_follows_latest

Assign to me and Reassign skipped every review ("cannot be assigned yet"). Rows are only ever added: the latest per
review is its assignee, the earlier ones the record. Tenant RLS as on trigger_events (0056).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0059_review_assignments"
down_revision = "0058_widget_follows_latest"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "review_assignments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("review_id", sa.String(200), nullable=False),
        sa.Column("assignee", sa.String(320), nullable=False),
        sa.Column("assigned_by", sa.String(320), nullable=False),
        sa.Column("assigned_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_review_assignments_review", "review_assignments", ["tenant_id", "review_id", "assigned_at"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(f"GRANT SELECT, INSERT ON review_assignments TO {TENANT_ROLE}")
    op.execute("ALTER TABLE review_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_assignments FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY review_assignments_tenant ON review_assignments "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS review_assignments_tenant ON review_assignments")
    op.drop_index("ix_review_assignments_review", table_name="review_assignments")
    op.drop_table("review_assignments")
