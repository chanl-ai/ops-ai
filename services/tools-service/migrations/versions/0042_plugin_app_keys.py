"""plugin_app_keys: the platform's own OAuth app secret per plugin, sealed, at the account (c-565)

An install registers one app per vendor and every team signs in with it unless the team brings its own. The secret
belongs to no team, so a team's secrets never serve another team's sign-in.

Revision ID: tools_0042_plugin_app_keys
Revises: tools_0041_plugin_bindings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0042_plugin_app_keys"
down_revision = "tools_0041_plugin_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugin_app_keys",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("plugin_id", sa.String(120), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("plugin_app_keys")
