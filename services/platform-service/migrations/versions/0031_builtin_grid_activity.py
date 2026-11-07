"""built-in grid: the activity area

The team's activity log of tool calls names who called which tool, so it has a cell of its own: reviewers, builders,
admins and security admins read it, viewers do not. Adds each missing cell and raises each tenant's permission
version; the downgrade removes the area's cells.

Revision ID: 0031_activity_cells
Revises: 0030_signin_secrets
"""

from __future__ import annotations

from alembic import op

revision = "0031_activity_cells"
down_revision = "0030_signin_secrets"
branch_labels = None
depends_on = None

EVERY = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")
CELLS = {
    "admin": EVERY,
    "builder": EVERY,
    "reviewer": ("view",),
    "security_admin": ("view",),
}


def upgrade() -> None:
    for role, actions in CELLS.items():
        for action in actions:
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, 'activity', '{action}', 'all' FROM roles r WHERE r.id = '{role}' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = 'activity' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE area = 'activity'")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
