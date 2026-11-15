"""built-in grid: the evals area

Saved eval cases and their runs have a cell of their own: every team role but chat user reads them; builders and
admins hold every cell, so they save cases and run them. Adds each missing cell and raises each tenant's permission
version; the downgrade removes the area's cells.

Revision ID: 0037_evals_cells
Revises: 0037_builder_connections
"""

from __future__ import annotations

from alembic import op

revision = "0037_evals_cells"
down_revision = "0037_builder_connections"
branch_labels = None
depends_on = None

EVERY = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")
CELLS = {
    "admin": EVERY,
    "builder": EVERY,
    "reviewer": ("view",),
    "viewer": ("view",),
}


def upgrade() -> None:
    for role, actions in CELLS.items():
        for action in actions:
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, 'evals', '{action}', 'all' FROM roles r WHERE r.id = '{role}' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = 'evals' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE area = 'evals'")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
