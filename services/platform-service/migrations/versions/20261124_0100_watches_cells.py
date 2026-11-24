"""built-in grid: the watches area

A watched folder copies an app's folders into the team's Files for every member, so adding, changing, checking and
deleting one has a cell of its own, watches.manage, held by Admin and Builder (each holds every cell of its kind, as the
catalogue grants). Reading a watch follows files.view, so no role is given watches.view. Adds each missing cell and
raises each tenant's permission version; the downgrade removes the area's cells.

Revision ID: 20261124_0100_watches_cells
Revises: 20261122_2022_list_sort_indexes
"""

from __future__ import annotations

from alembic import op

revision = "20261124_0100_watches_cells"
down_revision = "20261122_2022_list_sort_indexes"
branch_labels = None
depends_on = None

EVERY = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")
CELLS = {"admin": EVERY, "builder": EVERY}


def upgrade() -> None:
    for role, actions in CELLS.items():
        for action in actions:
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, 'watches', '{action}', 'all' FROM roles r WHERE r.id = '{role}' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = 'watches' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE area = 'watches'")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
