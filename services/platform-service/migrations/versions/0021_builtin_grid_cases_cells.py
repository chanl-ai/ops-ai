"""built-in grid: every member role opens and works its team's cases

Cases are long-lived customer issues (c-128). Builders, reviewers and viewers open a case and change its status,
assignee, priority and notes in their team; closing one stays on cases.manage. Admins hold these cells since 0016.
Adds each missing cell and raises each tenant's permission version; the downgrade removes exactly what it added.

Revision ID: 0021_cases_cells
Revises: 0020_team_secrets
"""

from __future__ import annotations

from alembic import op

revision = "0021_cases_cells"
down_revision = "0020_team_secrets"
branch_labels = None
depends_on = None

ROLES = ("builder", "reviewer", "viewer")
ACTIONS = ("create", "edit")


def upgrade() -> None:
    for role in ROLES:
        for action in ACTIONS:
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, 'cases', '{action}', 'all' FROM roles r WHERE r.id = '{role}' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = 'cases' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    for role in ROLES:
        for action in ACTIONS:
            op.execute(
                f"DELETE FROM role_permissions WHERE role_id = '{role}' AND area = 'cases' AND action = '{action}'"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
