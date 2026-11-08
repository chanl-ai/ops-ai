"""built-in grid: the webhooks and usage areas

A team's webhooks (endpoint addresses, delivery history) and its usage and cost are team-admin data, each with a cell
of its own so a custom role can be given one without access management. Admins hold every cell of both; no other
built-in role holds any. Adds each missing cell and raises each tenant's permission version; the downgrade removes them.

Revision ID: 0032_webhooks_usage_cells
Revises: 0031_activity_cells
"""

from __future__ import annotations

from alembic import op

revision = "0032_webhooks_usage_cells"
down_revision = "0031_activity_cells"
branch_labels = None
depends_on = None

AREAS = ("webhooks", "usage")
EVERY = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")


def upgrade() -> None:
    for area in AREAS:
        for action in EVERY:
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, '{area}', '{action}', 'all' FROM roles r WHERE r.id = 'admin' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = '{area}' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE area IN ('webhooks', 'usage')")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
