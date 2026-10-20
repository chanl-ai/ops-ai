"""skills as versioned attachments (c-063 slice 2)

Revision ID: 0026_skills
Revises: 0025_guardrails
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_skills"
down_revision = "0025_guardrails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registry_skills",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("owner_team", sa.String(200), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("published_version", sa.Integer),
        sa.Column("deprecated_reason", sa.Text),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("updated_by", sa.String(200), nullable=False),
    )
    op.create_table(
        "registry_skill_versions",
        sa.Column("skill_id", sa.String(64), sa.ForeignKey("registry_skills.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("tokens", sa.Integer, nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("changes", sa.JSON, nullable=False),
        sa.Column("saved_at", sa.String(32), nullable=False),
        sa.Column("saved_by", sa.String(200), nullable=False),
        sa.Column("published_at", sa.String(32)),
        sa.Column("published_by", sa.String(200)),
        sa.Column("review_id", sa.String(64)),
    )


def downgrade() -> None:
    op.drop_table("registry_skill_versions")
    op.drop_table("registry_skills")
