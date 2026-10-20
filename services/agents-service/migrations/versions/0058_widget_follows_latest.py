"""widget_deployments.agent_version may be null: a chat channel on Latest serves the agent's newest published version

Revision ID: 0058_widget_follows_latest
Revises: 0057_engine_step_node_type

A widget pinned a version, so every publish needed the embed moved by hand (c-245). Null means Latest: a new
conversation starts on the version published then. Existing rows keep their pin.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0058_widget_follows_latest"
down_revision = "0057_engine_step_node_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("widget_deployments", "agent_version", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute(
        "UPDATE widget_deployments SET agent_version = registry_agents.published_version FROM registry_agents "
        "WHERE widget_deployments.agent_version IS NULL AND registry_agents.id = widget_deployments.agent_id"
    )
    op.alter_column("widget_deployments", "agent_version", existing_type=sa.Integer(), nullable=False)
