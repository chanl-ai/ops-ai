"""agent registry: agents, their versions, and publish requests shared with workflows

Revision ID: 0016_agent_registry
Revises: 0015_thread_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_agent_registry"
down_revision = "0015_thread_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registry_agents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("owner", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("published_version", sa.Integer),
        sa.Column("paused", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "registry_agent_versions",
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("registry_agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("spec", sa.JSON, nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("changes", sa.JSON, nullable=False),
        sa.Column("saved_at", sa.String(32), nullable=False),
        sa.Column("saved_by", sa.String(200), nullable=False),
        sa.Column("published_at", sa.String(32)),
        sa.Column("published_by", sa.String(200)),
        sa.Column("review_id", sa.String(64)),
    )
    op.create_table(
        "registry_publish_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("decided_at", sa.String(32)),
        sa.Column("decided_by", sa.String(200)),
        sa.Column("body", sa.JSON, nullable=False),
    )
    op.create_index("ix_registry_publish_requests_subject", "registry_publish_requests", ["kind", "subject_id"])


def downgrade() -> None:
    op.drop_table("registry_publish_requests")
    op.drop_table("registry_agent_versions")
    op.drop_table("registry_agents")
