"""case_types, case_type_versions: the fields a case shows, in order (c-291); cases pin the type they were opened with

A case type is a versioned record like a task type (store/typed_records.py): its fields, each with a key, label and
type. A case pins the type's published version at open (`type_id`, `type_version`), so a later edit of the type never
changes a case already open. Tenant RLS as on task_types.

Revision ID: 0069_case_types
Revises: 0068_task_assists_fill
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0069_case_types"
down_revision = "0068_task_assists_fill"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"
TABLES = ("case_types", "case_type_versions")


def upgrade() -> None:
    op.create_table(
        "case_types",
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
        "case_type_versions",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("type_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("record", sa.JSON(), nullable=False),
        sa.Column("saved_at", sa.String(32), nullable=False),
        sa.Column("saved_by", sa.String(320), nullable=False),
        sa.Column("published_at", sa.String(32)),
        sa.Column("published_by", sa.String(320)),
    )
    op.add_column("cases", sa.Column("type_id", sa.String(64)))
    op.add_column("cases", sa.Column("type_version", sa.Integer()))
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
    op.drop_column("cases", "type_version")
    op.drop_column("cases", "type_id")
    for t in reversed(TABLES):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"DROP POLICY IF EXISTS {t}_tenant ON {t}")
        op.drop_table(t)
