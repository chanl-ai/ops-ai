"""built-in grid: the mcp area

A link's Calls tab reads the calls made through an MCP link with a cell of its own: builders and admins read everyone's,
reviewers and viewers their own. Adds each missing cell and raises each tenant's permission version; the
downgrade removes the area's cells.

Revision ID: 0037_mcp_cells
Revises: 0036_oauth_address_counts
"""

from __future__ import annotations

from alembic import op

revision = "0037_mcp_cells"
down_revision = "0036_oauth_address_counts"
branch_labels = None
depends_on = None

EVERY = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")
CELLS = {
    "admin": (EVERY, "all"),
    "builder": (EVERY, "all"),
    "reviewer": (("view",), "own"),
    "viewer": (("view",), "own"),
}


def upgrade() -> None:
    for role, (actions, scope) in CELLS.items():
        for action in actions:
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, 'mcp', '{action}', '{scope}' FROM roles r WHERE r.id = '{role}' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = 'mcp' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE area = 'mcp'")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
