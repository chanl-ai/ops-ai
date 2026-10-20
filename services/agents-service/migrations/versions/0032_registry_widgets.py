"""widget templates as versioned attachments (c-082)

Revision ID: 0032_registry_widgets
Revises: 0031_engine_definitions_stage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_registry_widgets"
down_revision = "0031_engine_definitions_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registry_widgets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("published_version", sa.Integer),
        sa.Column("retired_reason", sa.Text),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("updated_by", sa.String(200), nullable=False),
    )
    op.create_table(
        "registry_widget_versions",
        sa.Column(
            "widget_id", sa.String(64), sa.ForeignKey("registry_widgets.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("changes", sa.JSON, nullable=False),
        sa.Column("saved_at", sa.String(32), nullable=False),
        sa.Column("saved_by", sa.String(200), nullable=False),
        sa.Column("published_at", sa.String(32)),
        sa.Column("published_by", sa.String(200)),
        sa.Column("review_id", sa.String(64)),
    )


def downgrade() -> None:
    op.drop_table("registry_widget_versions")
    op.drop_table("registry_widgets")
