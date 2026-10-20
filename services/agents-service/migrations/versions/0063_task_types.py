"""task_types, task_type_versions: what a Human Task screen asks and offers, as versioned records (c-288)

A task screen was chosen by code for each kind of review, and a workflow's review step showed whatever text it was
given. A type is now a record a review step or the task API names by id and version; tenant RLS as on service_events
(0060).

Revision ID: 0063_task_types
Revises: 0062_case_fields
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0063_task_types"
down_revision = "0062_case_fields"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"
TABLES = ("task_types", "task_type_versions")


def upgrade() -> None:
    op.create_table(
        "task_types",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64)),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("published_version", sa.Integer()),
        sa.Column("copied_from", sa.JSON()),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
    )
    op.create_table(
        "task_type_versions",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("type_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("record", sa.JSON(), nullable=False),
        sa.Column("saved_at", sa.String(32), nullable=False),
        sa.Column("saved_by", sa.String(320), nullable=False),
        sa.Column("published_at", sa.String(32)),
        sa.Column("published_by", sa.String(320)),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    for t in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO {TENANT_ROLE}")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {t}_tenant ON {t} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    for t in reversed(TABLES):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"DROP POLICY IF EXISTS {t}_tenant ON {t}")
        op.drop_table(t)
