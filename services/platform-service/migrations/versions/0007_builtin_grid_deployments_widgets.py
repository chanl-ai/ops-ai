"""built-in grid: no delete for widgets or deployments, and polling a deployment is a run

0006 gave Admin and Builder `widgets.delete` and `deployments.delete`, but no route deletes either (a widget is
retired, a deployment paused), and it left out polling a deployment, which agents-service lets a builder or admin do
(`routers/channels.py`, `POST /v1/deployments/{id}/poll`). This brings every tenant's built-in Admin and Builder to
`ops_platform/permissions.py` and raises each tenant's permission version. Portable SQL only; the built-in ids are
reserved, so no custom role is matched.

Revision ID: 0007_grid_fixes
Revises: 0006_roles
"""

from __future__ import annotations

from alembic import op

revision = "0007_grid_fixes"
down_revision = "0006_roles"
branch_labels = None
depends_on = None

ROLES = "('admin', 'builder')"


def upgrade() -> None:
    op.execute(
        f"DELETE FROM role_permissions WHERE role_id IN {ROLES} "
        "AND area IN ('widgets', 'deployments') AND action = 'delete'"
    )
    op.execute(
        "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
        f"SELECT tenant_id, id, 'deployments', 'run', 'all' FROM roles WHERE id IN {ROLES}"
    )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute(f"DELETE FROM role_permissions WHERE role_id IN {ROLES} AND area = 'deployments' AND action = 'run'")
    for area in ("widgets", "deployments"):
        op.execute(
            "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
            f"SELECT tenant_id, id, '{area}', 'delete', 'all' FROM roles WHERE id IN {ROLES}"
        )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
