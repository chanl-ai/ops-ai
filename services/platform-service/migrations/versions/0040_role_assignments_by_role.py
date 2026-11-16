"""role assignments indexed by role

Who holds a role (the role's holders, the admins a team counts, the owner check) reads role_assignments by tenant and
role; with no index leading with the role, each read and each delete of a custom role scanned the tenant's
assignments. Adds the index; the downgrade drops it.

Revision ID: 0040_role_assignments_by_role
Revises: 0037_evals_cells
"""

from __future__ import annotations

from alembic import op

revision = "0040_role_assignments_by_role"
down_revision = "0037_evals_cells"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_role_assignments_role", "role_assignments", ["tenant_id", "role_id"])


def downgrade() -> None:
    op.drop_index("ix_role_assignments_role", table_name="role_assignments")
