"""built-in grid: every role corrects or forgets what agents remember about its own person

Correcting or forgetting a memory needs `memory.edit` (c-206), held for one's own memory only, by every built-in
role a person can hold (chat users included); API keys hold none. Adds the cell to every tenant's built-in roles and
raises each tenant's permission version. Portable SQL only; built-in ids are reserved, so no custom role is matched.

Revision ID: 0015_memory_edit
Revises: 0014_workspace_teams
"""

from __future__ import annotations

from alembic import op

revision = "0015_memory_edit"
down_revision = "0014_workspace_teams"
branch_labels = None
depends_on = None

ROLES = ("admin", "builder", "reviewer", "viewer", "chat_user")


def upgrade() -> None:
    ids = ", ".join(f"'{r}'" for r in ROLES)
    op.execute(
        "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
        f"SELECT tenant_id, id, 'memory', 'edit', 'own' FROM roles WHERE id IN ({ids})"
    )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE area = 'memory' AND action = 'edit'")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
