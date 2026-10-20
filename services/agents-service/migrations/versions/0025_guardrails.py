"""guardrails as versioned attachments (c-063)

Revision ID: 0025_guardrails
Revises: 0024_engine_runs_steps_work
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_guardrails"
down_revision = "0024_engine_runs_steps_work"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registry_guardrails",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("owner", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("published_version", sa.Integer),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "registry_guardrail_versions",
        sa.Column(
            "guardrail_id",
            sa.String(64),
            sa.ForeignKey("registry_guardrails.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("saved_at", sa.String(32), nullable=False),
        sa.Column("saved_by", sa.String(200), nullable=False),
        sa.Column("published_at", sa.String(32)),
        sa.Column("published_by", sa.String(200)),
        sa.Column("review_id", sa.String(64)),
    )


def downgrade() -> None:
    op.drop_table("registry_guardrail_versions")
    op.drop_table("registry_guardrails")
