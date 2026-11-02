"""connections.origin: "tool" for a connection the platform made to hold a custom tool's address (c-616)

The Apps grid lists the apps a person added (owner, 2026-11-01); a connection made for a tool is reached from the tool.
Existing ones are marked: those tools_0056 made (created_by "module address"), the dev seed's `con_mod_` ones, and an
auth-none connection a person's tool page made, named after the one module that uses it. The seed's integrations are
the demo's apps and stay listed.

Revision ID: tools_0059_connection_origin
Revises: tools_0058_module_address
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0059_connection_origin"
down_revision = "tools_0058_module_address"
branch_labels = None
depends_on = None

TOOL = "tool"


def upgrade() -> None:
    with op.batch_alter_table("connections") as b:
        b.add_column(sa.Column("origin", sa.String(16)))
    op.execute(f"""
        UPDATE connections SET origin = '{TOOL}'
        WHERE created_by = 'module address' OR id LIKE 'con_mod_%'
           OR (auth_kind = 'none' AND created_by NOT IN ('seed', 'dev seed') AND EXISTS (
                SELECT 1 FROM tool_modules m WHERE m.tenant_id = connections.tenant_id
                   AND m.connection_id = connections.id AND m.display_name = connections.name)
               AND NOT EXISTS (
                SELECT 1 FROM tool_modules m WHERE m.tenant_id = connections.tenant_id
                   AND m.connection_id = connections.id AND m.display_name <> connections.name))
    """)


def downgrade() -> None:
    with op.batch_alter_table("connections") as b:
        b.drop_column("origin")
