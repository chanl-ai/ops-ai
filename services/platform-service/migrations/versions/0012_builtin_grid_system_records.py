"""built-in grid: a team admin changes the records the platform provisions as system

Editing or deleting a record provisioned as `system` (c-180) needs `<area>.manage`; the owner decided admins may do
everything, builders not, and the next provisioning run puts back the fields the template owns. Adds `manage` on
agents, tools and knowledge to every tenant's admin role and raises each tenant's permission version. Portable SQL
only; built-in ids are reserved, so no custom role is matched.

Revision ID: 0012_system_records
Revises: 0011_policies
"""

from __future__ import annotations

from alembic import op

revision = "0012_system_records"
down_revision = "0011_policies"
branch_labels = None
depends_on = None

ADMIN_RULES = (("agents", "manage"), ("tools", "manage"), ("knowledge", "manage"))


def upgrade() -> None:
    for area, action in ADMIN_RULES:
        op.execute(
            "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
            f"SELECT tenant_id, id, '{area}', '{action}', 'all' FROM roles WHERE id = 'admin'"
        )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    for area, action in ADMIN_RULES:
        op.execute(f"DELETE FROM role_permissions WHERE role_id = 'admin' AND area = '{area}' AND action = '{action}'")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
