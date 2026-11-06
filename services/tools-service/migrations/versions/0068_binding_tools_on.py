"""binding_tools_on: the tools a team lets its agents and workflows use, per app

Agents could pick any tool of an app the team turned on, write tools included, before anyone chose them. The team's
binding now keeps the tools switched on; null keeps every tool on, as for apps turned on before the switch.

Revision ID: tools_0068_binding_tools_on
Revises: tools_0067_run_kind_live
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0068_binding_tools_on"
down_revision = "tools_0067_run_kind_live"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plugin_bindings", sa.Column("tools_on", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("plugin_bindings") as b:
        b.drop_column("tools_on")
