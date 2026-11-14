"""built-in grid: builders read connections and secrets, admins change them

D59 keeps the workspace's settings, connections, secrets and auth configs included, out of the builder role; only
reading them stays (`view`, which every member holds). Removes every other builder cell on `connections` and
`secrets_egress` from each tenant's stored grid, an admin's edit of the builder role included, since the default is
what changed, and raises each tenant's permission version. The downgrade puts back the cells 0028 gave.

Revision ID: 0037_builder_connections
Revises: 0036_oauth_address_counts
"""

from __future__ import annotations

from alembic import op

revision = "0037_builder_connections"
down_revision = "0036_oauth_address_counts"
branch_labels = None
depends_on = None

AREAS = ("connections", "secrets_egress")
TAKEN = ("create", "edit", "publish", "delete", "run", "decide", "manage")


def upgrade() -> None:
    areas = ", ".join(f"'{a}'" for a in AREAS)
    op.execute(f"DELETE FROM role_permissions WHERE role_id = 'builder' AND area IN ({areas}) AND action <> 'view'")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    for area in AREAS:
        for action in TAKEN:
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, '{area}', '{action}', 'all' FROM roles r WHERE r.id = 'builder' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = '{area}' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
