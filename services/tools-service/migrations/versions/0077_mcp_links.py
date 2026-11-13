"""mcp_links and gateway_calls.link_id: a named address for a chosen set of one team's tools

A team had one MCP address that listed every read tool it may run. A link names a chosen set at its own address
(`/mcp/<team>/<slug>`), and each call through it records the link, so the link's page lists its own calls.

Revision ID: tools_0077_mcp_links
Revises: tools_0076_account_owner_key
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0077_mcp_links"
down_revision = "tools_0076_account_owner_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_links",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("tools", sa.JSON, nullable=False),
        sa.Column("paused", sa.Boolean, nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("tenant_id", "team_id", "slug", name="uq_mcp_links_team_slug"),
    )
    op.add_column("gateway_calls", sa.Column("link_id", sa.String(64)))
    op.create_index("ix_gateway_calls_link_created", "gateway_calls", ["link_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_gateway_calls_link_created", table_name="gateway_calls")
    op.drop_column("gateway_calls", "link_id")
    op.drop_table("mcp_links")
