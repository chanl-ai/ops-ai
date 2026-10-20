"""built-in grid: the connections area

Connections hold how the platform signs in to each system (tools-service, c-330), checked as `connections`. Every
member reads them; admins hold every cell, `manage` (create, change, set secret parts, sign in) included (owner,
2026-10-19). Adds each missing cell and raises each tenant's permission version.

Revision ID: 0025_connections_cells
Revises: 0024_signin_email_failures
"""

from __future__ import annotations

from alembic import op

revision = "0025_connections_cells"
down_revision = "0024_signin_email_failures"
branch_labels = None
depends_on = None

CELLS = {
    "admin": ("view", "create", "edit", "publish", "delete", "run", "decide", "manage"),
    "builder": ("view",),
    "reviewer": ("view",),
    "viewer": ("view",),
}


def upgrade() -> None:
    for role, actions in CELLS.items():
        for action in actions:
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, 'connections', '{action}', 'all' FROM roles r WHERE r.id = '{role}' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = 'connections' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    pass
