"""built-in grid: a team's builders add, change and remove that team's secrets

A team's secrets are its own (owner, 2026-10-17; c-186): builders now hold `secrets_egress` create, edit and delete,
checked in the team that owns the secret; the egress list and workspace-wide secrets stay with the Security team
(`manage`), and the `securityTeamAddsSecrets` policy moves team writes back there. Admins already hold every cell
(0016). Adds the builder rows in every tenant, once, and raises each tenant's permission version. Portable SQL only.

Revision ID: 0020_team_secrets
Revises: 0019_signin_lockouts
"""

from __future__ import annotations

from alembic import op

revision = "0020_team_secrets"
down_revision = "0019_signin_lockouts"
branch_labels = None
depends_on = None

ACTIONS = ("create", "edit", "delete")


def upgrade() -> None:
    for action in ACTIONS:
        op.execute(
            "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
            f"SELECT r.tenant_id, r.id, 'secrets_egress', '{action}', 'all' FROM roles r WHERE r.id = 'builder' "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id AND p.role_id = r.id "
            f"AND p.area = 'secrets_egress' AND p.action = '{action}')"
        )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    for action in ACTIONS:
        op.execute(
            "DELETE FROM role_permissions WHERE role_id = 'builder' AND area = 'secrets_egress' "
            f"AND action = '{action}'"
        )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
