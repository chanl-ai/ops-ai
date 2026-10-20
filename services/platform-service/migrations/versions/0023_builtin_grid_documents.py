"""built-in grid: the documents area

Document types, extractions and corrections moved to their own service (c-256), checked as `documents`. Builders,
reviewers and viewers read and extract files and keep the team's document types and samples; admins hold every cell;
`delete` (purging what was derived from a file) is for admins and the workflow that runs when a file is deleted. Adds
each missing cell and raises each tenant's permission version.

Revision ID: 0023_documents_cells
Revises: 0022_api_key_target
"""

from __future__ import annotations

from alembic import op

revision = "0023_documents_cells"
down_revision = "0022_api_key_target"
branch_labels = None
depends_on = None

CELLS = {
    "admin": ("view", "create", "edit", "publish", "delete", "run", "decide", "manage"),
    "builder": ("view", "edit", "run"),
    "reviewer": ("view", "edit", "run"),
    "viewer": ("view", "edit", "run"),
}


def upgrade() -> None:
    for role, actions in CELLS.items():
        for action in actions:
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, 'documents', '{action}', 'all' FROM roles r WHERE r.id = '{role}' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = 'documents' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    pass
