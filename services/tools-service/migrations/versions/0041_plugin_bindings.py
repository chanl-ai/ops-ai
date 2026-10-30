"""plugin_bindings: each team's part of a plugin, its switch, connection and settings (c-564)

A plugin's tools are one workspace-level module, which holds one connection, endpoint and egress list for every team,
so team A's calls would use team B's. The gateway reads those from the calling team's row here instead.

Revision ID: tools_0041_plugin_bindings
Revises: tools_0040_operation_scopes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0041_plugin_bindings"
down_revision = "tools_0040_operation_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugin_bindings",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), primary_key=True),
        sa.Column("plugin_id", sa.String(120), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("connection_id", sa.String(64)),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("plugin_bindings")
