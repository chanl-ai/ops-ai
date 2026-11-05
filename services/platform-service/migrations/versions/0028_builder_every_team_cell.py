"""built-in grid: a builder holds every cell but people and access and the workspace's settings

Decided 2026-11-05 (D59): builders do everything in their team except people and access (members, roles,
assignments) and the workspace's settings: connections, secrets and auth configs included. Sets every tenant's builder
role to that grid, adding each missing cell and widening a cell held on one's own records to every record, and raises
each tenant's permission version. Both grids are frozen here as they stood; a later change needs its own migration.
A tenant whose admin edited the builder role is moved to the new default too, since the default is what changed.
Portable SQL only; built-in ids are reserved.

Revision ID: 0028_builder_every_team_cell
Revises: 0027_platform_outbox
"""

from __future__ import annotations

from alembic import op

revision = "0028_builder_every_team_cell"
down_revision = "0027_platform_outbox"
branch_labels = None
depends_on = None

# The builder role's grid after this revision.
AFTER = (
    ("access", "view", "all"),
    ("agents", "create", "all"),
    ("agents", "decide", "all"),
    ("agents", "delete", "all"),
    ("agents", "edit", "all"),
    ("agents", "manage", "all"),
    ("agents", "publish", "all"),
    ("agents", "run", "all"),
    ("agents", "view", "all"),
    ("audit", "create", "all"),
    ("audit", "decide", "all"),
    ("audit", "delete", "all"),
    ("audit", "edit", "all"),
    ("audit", "manage", "all"),
    ("audit", "publish", "all"),
    ("audit", "run", "all"),
    ("audit", "view", "all"),
    ("cases", "create", "all"),
    ("cases", "decide", "all"),
    ("cases", "delete", "all"),
    ("cases", "edit", "all"),
    ("cases", "manage", "all"),
    ("cases", "publish", "all"),
    ("cases", "run", "all"),
    ("cases", "view", "all"),
    ("chat", "create", "all"),
    ("chat", "decide", "all"),
    ("chat", "delete", "all"),
    ("chat", "edit", "all"),
    ("chat", "manage", "all"),
    ("chat", "publish", "all"),
    ("chat", "run", "all"),
    ("chat", "view", "all"),
    ("connections", "create", "all"),
    ("connections", "decide", "all"),
    ("connections", "delete", "all"),
    ("connections", "edit", "all"),
    ("connections", "manage", "all"),
    ("connections", "publish", "all"),
    ("connections", "run", "all"),
    ("connections", "view", "all"),
    ("deployments", "create", "all"),
    ("deployments", "decide", "all"),
    ("deployments", "delete", "all"),
    ("deployments", "edit", "all"),
    ("deployments", "manage", "all"),
    ("deployments", "publish", "all"),
    ("deployments", "run", "all"),
    ("deployments", "view", "all"),
    ("documents", "create", "all"),
    ("documents", "decide", "all"),
    ("documents", "delete", "all"),
    ("documents", "edit", "all"),
    ("documents", "manage", "all"),
    ("documents", "publish", "all"),
    ("documents", "run", "all"),
    ("documents", "view", "all"),
    ("files", "create", "all"),
    ("files", "decide", "all"),
    ("files", "delete", "all"),
    ("files", "edit", "all"),
    ("files", "manage", "all"),
    ("files", "publish", "all"),
    ("files", "run", "all"),
    ("files", "view", "all"),
    ("guardrails", "create", "all"),
    ("guardrails", "decide", "all"),
    ("guardrails", "delete", "all"),
    ("guardrails", "edit", "all"),
    ("guardrails", "manage", "all"),
    ("guardrails", "publish", "all"),
    ("guardrails", "run", "all"),
    ("guardrails", "view", "all"),
    ("knowledge", "create", "all"),
    ("knowledge", "decide", "all"),
    ("knowledge", "delete", "all"),
    ("knowledge", "edit", "all"),
    ("knowledge", "manage", "all"),
    ("knowledge", "publish", "all"),
    ("knowledge", "run", "all"),
    ("knowledge", "view", "all"),
    ("memory", "create", "all"),
    ("memory", "decide", "all"),
    ("memory", "delete", "all"),
    ("memory", "edit", "own"),
    ("memory", "manage", "all"),
    ("memory", "publish", "all"),
    ("memory", "run", "all"),
    ("memory", "view", "all"),
    ("reviews", "create", "all"),
    ("reviews", "decide", "all"),
    ("reviews", "delete", "all"),
    ("reviews", "edit", "all"),
    ("reviews", "manage", "all"),
    ("reviews", "publish", "all"),
    ("reviews", "run", "all"),
    ("reviews", "view", "all"),
    ("secrets_egress", "create", "all"),
    ("secrets_egress", "decide", "all"),
    ("secrets_egress", "delete", "all"),
    ("secrets_egress", "edit", "all"),
    ("secrets_egress", "manage", "all"),
    ("secrets_egress", "publish", "all"),
    ("secrets_egress", "run", "all"),
    ("secrets_egress", "view", "all"),
    ("skills", "create", "all"),
    ("skills", "decide", "all"),
    ("skills", "delete", "all"),
    ("skills", "edit", "all"),
    ("skills", "manage", "all"),
    ("skills", "publish", "all"),
    ("skills", "run", "all"),
    ("skills", "view", "all"),
    ("tools", "create", "all"),
    ("tools", "decide", "all"),
    ("tools", "delete", "all"),
    ("tools", "edit", "all"),
    ("tools", "manage", "all"),
    ("tools", "publish", "all"),
    ("tools", "run", "all"),
    ("tools", "view", "all"),
    ("widgets", "create", "all"),
    ("widgets", "decide", "all"),
    ("widgets", "delete", "all"),
    ("widgets", "edit", "all"),
    ("widgets", "manage", "all"),
    ("widgets", "publish", "all"),
    ("widgets", "run", "all"),
    ("widgets", "view", "all"),
    ("workflows", "create", "all"),
    ("workflows", "decide", "all"),
    ("workflows", "delete", "all"),
    ("workflows", "edit", "all"),
    ("workflows", "manage", "all"),
    ("workflows", "publish", "all"),
    ("workflows", "run", "all"),
    ("workflows", "view", "all"),
)
# And before it, so the downgrade puts back exactly what was there.
BEFORE = (
    ("access", "view", "all"),
    ("agents", "create", "all"),
    ("agents", "delete", "all"),
    ("agents", "edit", "all"),
    ("agents", "publish", "all"),
    ("agents", "run", "all"),
    ("agents", "view", "all"),
    ("cases", "create", "all"),
    ("cases", "edit", "all"),
    ("cases", "manage", "own"),
    ("cases", "view", "all"),
    ("chat", "run", "all"),
    ("chat", "view", "own"),
    ("connections", "view", "all"),
    ("deployments", "create", "all"),
    ("deployments", "edit", "all"),
    ("deployments", "run", "all"),
    ("deployments", "view", "all"),
    ("documents", "edit", "all"),
    ("documents", "run", "all"),
    ("documents", "view", "all"),
    ("files", "create", "all"),
    ("files", "delete", "all"),
    ("files", "view", "all"),
    ("guardrails", "create", "all"),
    ("guardrails", "delete", "own"),
    ("guardrails", "edit", "all"),
    ("guardrails", "publish", "all"),
    ("guardrails", "view", "all"),
    ("knowledge", "create", "all"),
    ("knowledge", "delete", "all"),
    ("knowledge", "edit", "all"),
    ("knowledge", "view", "all"),
    ("memory", "edit", "own"),
    ("reviews", "view", "all"),
    ("secrets_egress", "create", "all"),
    ("secrets_egress", "delete", "all"),
    ("secrets_egress", "edit", "all"),
    ("secrets_egress", "view", "all"),
    ("skills", "create", "all"),
    ("skills", "delete", "own"),
    ("skills", "edit", "all"),
    ("skills", "publish", "all"),
    ("skills", "view", "all"),
    ("tools", "create", "all"),
    ("tools", "delete", "all"),
    ("tools", "edit", "all"),
    ("tools", "publish", "all"),
    ("tools", "run", "all"),
    ("tools", "view", "all"),
    ("widgets", "create", "all"),
    ("widgets", "edit", "all"),
    ("widgets", "publish", "all"),
    ("widgets", "view", "all"),
    ("workflows", "create", "all"),
    ("workflows", "delete", "all"),
    ("workflows", "edit", "all"),
    ("workflows", "publish", "all"),
    ("workflows", "run", "all"),
    ("workflows", "view", "all"),
)


def _set(cells: tuple[tuple[str, str, str], ...]) -> None:
    """Every tenant's builder role holds exactly `cells`: others removed, each scope set, each missing one added."""
    held = " OR ".join(f"(area = '{a}' AND action = '{x}')" for a, x, _ in cells)
    op.execute(f"DELETE FROM role_permissions WHERE role_id = 'builder' AND NOT ({held})")
    for area, action, scope in cells:
        op.execute(
            f"UPDATE role_permissions SET scope = '{scope}' WHERE role_id = 'builder' AND area = '{area}' "
            f"AND action = '{action}' AND scope <> '{scope}'"
        )
        op.execute(
            "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
            f"SELECT r.tenant_id, r.id, '{area}', '{action}', '{scope}' FROM roles r WHERE r.id = 'builder' "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
            f"AND p.role_id = r.id AND p.area = '{area}' AND p.action = '{action}')"
        )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def upgrade() -> None:
    _set(AFTER)


def downgrade() -> None:
    _set(BEFORE)
