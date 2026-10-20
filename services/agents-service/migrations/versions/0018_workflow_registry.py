"""workflow registry: console workflows, their published graphs, and validation runs

Revision ID: 0018_workflow_registry
Revises: 0017_drop_chat_tables
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_workflow_registry"
down_revision = "0017_drop_chat_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registry_workflows",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("owner", sa.String(200), nullable=False),
        sa.Column("trigger", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("published_version", sa.Integer),
        sa.Column("draft", sa.JSON),
        sa.Column("draft_saved_at", sa.String(32)),
        sa.Column("draft_saved_by", sa.String(200)),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "registry_workflow_versions",
        sa.Column(
            "workflow_id",
            sa.String(64),
            sa.ForeignKey("registry_workflows.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("graph", sa.JSON, nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("changes", sa.JSON, nullable=False),
        sa.Column("published_at", sa.String(32), nullable=False),
        sa.Column("published_by", sa.String(200), nullable=False),
        sa.Column("review_id", sa.String(64)),
    )
    op.create_table(
        "registry_validations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(64), nullable=False, index=True),
        sa.Column("ran_at", sa.String(32), nullable=False),
        sa.Column("target", sa.String(8), nullable=False),
        sa.Column("results", sa.JSON, nullable=False),
        sa.Column("summary", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("registry_validations")
    op.drop_table("registry_workflow_versions")
    op.drop_table("registry_workflows")
